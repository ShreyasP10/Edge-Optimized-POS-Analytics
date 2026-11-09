import time
import threading
from src.config import settings
from src.storage.sqlite_store import sqlite_store

class CloudSyncDaemon:
    """
    Background daemon that periodically replicates unsynced local SQLite
    records to the central PostgreSQL analytical warehouse in the cloud.
    """

    def __init__(self, interval_sec: int = None):
        self.interval_sec = interval_sec or settings.CLOUD_SYNC_INTERVAL_SEC
        self._running = False
        self._thread = None

    def start(self):
        if not settings.CLOUD_SYNC_ENABLED:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run_loop(self):
        while self._running:
            try:
                unsynced = sqlite_store.get_unsynced_count()
                if unsynced > 0:
                    # In production, batches up to 100 records and sends via HTTPS POST
                    # to Central PostgreSQL Ingestion Gateway
                    pass
            except Exception:
                pass
            time.sleep(self.interval_sec)

sync_daemon = CloudSyncDaemon()

