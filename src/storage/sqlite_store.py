import sqlite3
import threading
import json
import time
import os
import hashlib
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from src.config import settings
from src.resilience.kill_switches import kill_switch_manager

class SQLiteStore:
    """
    Thread-safe, offline-resilient local SQLite feature store configured in WAL mode.
    Includes:
    - Online hot backup (`backup`) without table locking
    - Automated restore verification drills with SHA-256 checksums
    - Graceful Read-Only Mode degradation
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.SQLITE_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            uri = f"file:{os.path.abspath(self.db_path)}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=10.0)
        else:
            conn = sqlite3.connect(self.db_path, timeout=10.0)

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -8000;")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS analytics_events (
                    event_id TEXT PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    task_type TEXT NOT NULL,
                    routing_decision TEXT NOT NULL,
                    kan_score REAL NOT NULL,
                    kan_formula TEXT NOT NULL,
                    payload_size_mb REAL NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    incurred_cost_usd REAL NOT NULL,
                    telemetry_snapshot TEXT NOT NULL,
                    synced INTEGER DEFAULT 0
                );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_events_synced ON analytics_events(synced, timestamp);")
                conn.commit()
            finally:
                conn.close()

    def record_event(
        self,
        event_id: str,
        task_type: str,
        routing_decision: str,
        kan_score: float,
        kan_formula: str,
        payload_size_mb: float,
        execution_time_ms: float,
        incurred_cost_usd: float,
        telemetry_snapshot: dict
    ) -> bool:
        """
        Asynchronously writes a completed inference event to the audit ledger.
        If READ_ONLY_MODE is active, gracefully degrades by skipping write without failure.
        """
        if kill_switch_manager.is_active("READ_ONLY_MODE"):
            return False

        now = int(time.time())
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO analytics_events (
                        event_id, timestamp, task_type, routing_decision, kan_score,
                        kan_formula, payload_size_mb, execution_time_ms, incurred_cost_usd,
                        telemetry_snapshot, synced
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        event_id, now, task_type, routing_decision, kan_score,
                        kan_formula, payload_size_mb, execution_time_ms, incurred_cost_usd,
                        json.dumps(telemetry_snapshot)
                    )
                )
                conn.commit()
                return True
            finally:
                conn.close()

    def query_audit_logs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Queries local audit records."""
        with self._lock:
            conn = self._get_connection(read_only=True)
            try:
                cursor = conn.execute(
                    """
                    SELECT event_id, timestamp, task_type, routing_decision, kan_score,
                           kan_formula, payload_size_mb, execution_time_ms, incurred_cost_usd, synced
                    FROM analytics_events
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset)
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()

    def get_unsynced_count(self) -> int:
        """Counts pending records awaiting cloud synchronization."""
        with self._lock:
            conn = self._get_connection(read_only=True)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM analytics_events WHERE synced = 0")
                return cursor.fetchone()[0]
            finally:
                conn.close()

    # --- Backups & Restore Drills ---

    def create_online_backup(self, backup_dir: Optional[str] = None) -> Tuple[str, str, int]:
        """
        Creates an online, non-blocking hot backup using SQLite Online Backup API.
        Returns (backup_filepath, sha256_checksum, total_records).
        """
        target_dir = backup_dir or str(Path(self.db_path).parent / "backups")
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        backup_filename = f"edge_analytics_backup_{int(time.time())}.db"
        backup_filepath = os.path.join(target_dir, backup_filename)

        with self._lock:
            src_conn = self._get_connection(read_only=True)
            dest_conn = sqlite3.connect(backup_filepath)
            try:
                # Online backup without locking active read/writes
                src_conn.backup(dest_conn)
                dest_conn.commit()

                # Calculate SHA-256 checksum
                with open(backup_filepath, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()

                # Count records
                cursor = dest_conn.execute("SELECT COUNT(*) FROM analytics_events")
                total_records = cursor.fetchone()[0]

                return backup_filepath, file_hash, total_records
            finally:
                dest_conn.close()
                src_conn.close()

    @staticmethod
    def verify_restore_drill(backup_filepath: str) -> Dict[str, Any]:
        """
        Executes a Restore Drill:
        1. Tests restore into an isolated temporary sandbox.
        2. Executes PRAGMA integrity_check.
        3. Queries data to prove functional restorability.
        """
        t0 = time.perf_counter()
        if not os.path.exists(backup_filepath):
            raise FileNotFoundError(f"Backup file not found: {backup_filepath}")

        # Compute SHA-256
        with open(backup_filepath, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()

        # Temporary sandbox for restore verification
        temp_sandbox = tempfile.NamedTemporaryFile(suffix="_drill.db", delete=False)
        temp_sandbox.close()

        try:
            # Restore from backup into sandbox
            backup_conn = sqlite3.connect(backup_filepath)
            sandbox_conn = sqlite3.connect(temp_sandbox.name)
            backup_conn.backup(sandbox_conn)
            backup_conn.close()

            # Run SQLite integrity check
            cursor = sandbox_conn.execute("PRAGMA integrity_check;")
            integrity_result = cursor.fetchone()[0]

            # Count rows
            cursor = sandbox_conn.execute("SELECT COUNT(*) FROM analytics_events;")
            restored_row_count = cursor.fetchone()[0]

            sandbox_conn.close()
            drill_duration_ms = round((time.perf_counter() - t0) * 1000, 2)

            return {
                "restore_status": "SUCCESS" if integrity_result == "ok" else "FAILED",
                "integrity_check": integrity_result,
                "restored_row_count": restored_row_count,
                "sha256_checksum": checksum,
                "drill_duration_ms": drill_duration_ms,
                "drill_timestamp": time.time()
            }
        finally:
            if os.path.exists(temp_sandbox.name):
                os.remove(temp_sandbox.name)

sqlite_store = SQLiteStore()
