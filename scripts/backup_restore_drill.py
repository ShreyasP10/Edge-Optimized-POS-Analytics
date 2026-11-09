import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.storage.sqlite_store import sqlite_store

def run_backup_and_restore_drill():
    print("=" * 80)
    print("      KAN-EDGE POS ANALYTICS: HOT BACKUP & RESTORE VERIFICATION DRILL")
    print("=" * 80)
    print("[*] Testing live SQLite database online backup (non-blocking)...")

    # Step 1: Create hot backup
    t0 = time.perf_counter()
    backup_path, checksum, record_count = sqlite_store.create_online_backup()
    backup_time_ms = (time.perf_counter() - t0) * 1000

    print(f"[+] Hot Backup Created Successfully in {backup_time_ms:.2f} ms")
    print(f"    - Target Path:    {backup_path}")
    print(f"    - SHA-256 Hash:   {checksum}")
    print(f"    - Active Records: {record_count}")

    # Step 2: Execute automated restore drill into sandbox
    print("\n[*] Executing Restore Verification Drill into isolated sandbox...")
    drill_result = sqlite_store.verify_restore_drill(backup_path)

    print(f"[+] Restore Verification Status: {drill_result['restore_status']}")
    print(f"    - Integrity Check Result:  {drill_result['integrity_check']}")
    print(f"    - Restored Row Count:      {drill_result['restored_row_count']}")
    print(f"    - Drill Duration:          {drill_result['drill_duration_ms']} ms")

    # Step 3: Validate drill success
    assert drill_result["restore_status"] == "SUCCESS", "Restore drill failed!"
    assert drill_result["integrity_check"] == "ok", "Database corruption detected!"
    assert drill_result["restored_row_count"] == record_count, "Row count mismatch after restore!"

    print("\n" + "=" * 80)
    print("[PASSED] BACKUP & RESTORE DRILL CERTIFIED: Zero data corruption, 100% restorability.")
    print("=" * 80)

if __name__ == "__main__":
    run_backup_and_restore_drill()
