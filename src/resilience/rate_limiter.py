import time
import threading
from typing import Dict, Tuple

class RateLimiter:
    """
    Token-bucket rate limiter with sliding window quota enforcement.
    Applies per User / Terminal Token / Client IP to protect edge APU resources
    and prevent runaway cloud offload billing.
    """

    def __init__(
        self,
        rate_per_sec: float = 10.0,
        burst_capacity: int = 20,
        daily_quota: int = 50000
    ):
        self.rate_per_sec = rate_per_sec
        self.burst_capacity = burst_capacity
        self.daily_quota = daily_quota

        self._lock = threading.Lock()
        # Per-key state: { key: { "tokens": float, "last_update": float, "daily_count": int, "daily_reset": float } }
        self._clients: Dict[str, dict] = {}

    def is_allowed(self, client_key: str, cost: int = 1) -> Tuple[bool, dict]:
        """
        Evaluates whether a request from client_key is permitted.
        Returns (is_allowed, rate_limit_metadata).
        """
        now = time.time()

        with self._lock:
            client = self._clients.get(client_key)
            if not client:
                client = {
                    "tokens": float(self.burst_capacity),
                    "last_update": now,
                    "daily_count": 0,
                    "daily_reset": now + 86400.0
                }
                self._clients[client_key] = client

            # Daily quota check & reset
            if now >= client["daily_reset"]:
                client["daily_count"] = 0
                client["daily_reset"] = now + 86400.0

            if client["daily_count"] + cost > self.daily_quota:
                return False, {
                    "reason": "DAILY_QUOTA_EXCEEDED",
                    "daily_limit": self.daily_quota,
                    "daily_count": client["daily_count"],
                    "retry_after_sec": int(client["daily_reset"] - now)
                }

            # Refill tokens based on elapsed time
            elapsed = now - client["last_update"]
            client["tokens"] = min(
                float(self.burst_capacity),
                client["tokens"] + elapsed * self.rate_per_sec
            )
            client["last_update"] = now

            if client["tokens"] >= cost:
                client["tokens"] -= cost
                client["daily_count"] += cost
                return True, {
                    "allowed": True,
                    "remaining_tokens": round(client["tokens"], 1),
                    "daily_count": client["daily_count"],
                    "daily_limit": self.daily_quota
                }
            else:
                # Rate limited
                missing_tokens = cost - client["tokens"]
                retry_after = missing_tokens / self.rate_per_sec
                return False, {
                    "reason": "RATE_LIMIT_EXCEEDED",
                    "remaining_tokens": round(client["tokens"], 1),
                    "retry_after_sec": max(1, int(retry_after + 0.99)),
                    "daily_count": client["daily_count"],
                    "daily_limit": self.daily_quota
                }

    def reset_client(self, client_key: str):
        """Administrative reset of a client's bucket."""
        with self._lock:
            if client_key in self._clients:
                del self._clients[client_key]

# Default rate limiter for edge analytics tasks
edge_task_rate_limiter = RateLimiter(
    rate_per_sec=15.0,     # Max 15 camera batches/sec per terminal
    burst_capacity=30,     # Allow burst of up to 30 frames
    daily_quota=40000      # 40,000 analytics tasks per store terminal per day
)
