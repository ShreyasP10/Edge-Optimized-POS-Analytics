import sqlite3
import threading
import json
import time
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.config import settings

class SQLiteStore:
    """
    Thread-safe, offline-resilient local SQLite feature store configured in WAL mode.
    Maintains the mathematical KAN audit trail and feature logs locally during network drops.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.SQLITE_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
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
    ):
        """Asynchronously writes a completed inference event to the audit ledger."""
        now = int(time.time())
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO analytics_events (
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
            finally:
                conn.close()

    def query_audit_logs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Queries local audit records."""
        with self._lock:
            conn = self._get_connection()
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
            conn = self._get_connection()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM analytics_events WHERE synced = 0")
                return cursor.fetchone()[0]
            finally:
                conn.close()

sqlite_store = SQLiteStore()

