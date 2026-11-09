import time
import threading
from typing import Optional, Dict, Any, Tuple

class IdempotencyManager:
    """
    Guarantees idempotency for task execution and financial audit writes.
    Prevents duplicate inference, double billing, or corrupted ledger state
    when network dropouts cause upstream clients to retransmit requests.
    """

    def __init__(self, ttl_sec: float = 86400.0):  # 24-hour default retention
        self.ttl_sec = ttl_sec
        self._lock = threading.Lock()
        # Key -> { "status": "IN_PROGRESS" | "COMPLETED", "response": dict, "created_at": float }
        self._store: Dict[str, dict] = {}

    def get_or_create(self, idempotency_key: str) -> Tuple[str, Optional[dict]]:
        """
        Atomically inspects the idempotency key.
        Returns ("HIT", cached_response), ("IN_PROGRESS", None), or ("NEW", None).
        """
        now = time.time()
        with self._lock:
            # Purge expired keys periodically
            self._cleanup_expired(now)

            if idempotency_key in self._store:
                entry = self._store[idempotency_key]
                if entry["status"] == "COMPLETED":
                    return "HIT", entry["response"]
                elif entry["status"] == "IN_PROGRESS":
                    return "IN_PROGRESS", None

            # Register key as in-progress
            self._store[idempotency_key] = {
                "status": "IN_PROGRESS",
                "response": None,
                "created_at": now
            }
            return "NEW", None

    def complete(self, idempotency_key: str, response_payload: dict):
        """Marks the key as completed and caches the exact response."""
        with self._lock:
            if idempotency_key in self._store:
                self._store[idempotency_key]["status"] = "COMPLETED"
                self._store[idempotency_key]["response"] = response_payload

    def release(self, idempotency_key: str):
        """Releases the key in case of an uncaught error to allow immediate retry."""
        with self._lock:
            if idempotency_key in self._store:
                del self._store[idempotency_key]

    def _cleanup_expired(self, now: float):
        cutoff = now - self.ttl_sec
        expired = [k for k, v in self._store.items() if v["created_at"] < cutoff]
        for k in expired:
            del self._store[k]

idempotency_manager = IdempotencyManager()
