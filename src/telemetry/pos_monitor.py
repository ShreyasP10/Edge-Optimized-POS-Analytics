import time
import threading
from collections import deque

class POSMonitor:
    """
    Monitors live Point-of-Sale (POS) cashier checkout activity, including:
    - Active checkout transactions in progress
    - Barcode scanner pulse frequency (items scanned per second)
    - Emergency preemption triggers ("Billing Always Wins")
    """

    def __init__(self, rolling_window_sec: float = 5.0):
        self.rolling_window_sec = rolling_window_sec
        self._lock = threading.Lock()
        self._scan_timestamps = deque()
        self._active_transactions = 0
        self._payment_terminal_busy = False
        self._manual_override_active = False

    def record_scan_event(self):
        """Called when a cashier scans an item barcode."""
        now = time.time()
        with self._lock:
            self._scan_timestamps.append(now)
            if self._active_transactions == 0:
                self._active_transactions = 1

    def set_active_transactions(self, count: int):
        """Updates active checkout customer count."""
        with self._lock:
            self._active_transactions = max(0, count)

    def set_payment_state(self, is_busy: bool):
        """Updates EMV PIN pad transaction state."""
        with self._lock:
            self._payment_terminal_busy = is_busy

    def get_scan_rate(self) -> float:
        """Calculates items scanned per second over the rolling window."""
        now = time.time()
        cutoff = now - self.rolling_window_sec
        with self._lock:
            while self._scan_timestamps and self._scan_timestamps[0] < cutoff:
                self._scan_timestamps.popleft()
            count = len(self._scan_timestamps)
            return round(count / self.rolling_window_sec, 2)

    def get_checkout_pressure_index(self) -> float:
        """
        Computes normalized checkout pressure x2 in [0.0, 1.0].
        Formula: clamp((ActiveTransactions + 0.5 * ScanRate) / 10, 0, 1)
        """
        scan_rate = self.get_scan_rate()
        with self._lock:
            tx = self._active_transactions
            if self._payment_terminal_busy:
                tx += 2  # Strong penalty for active credit card processing

        raw_pressure = (tx + 0.5 * scan_rate) / 10.0
        return max(0.0, min(1.0, round(raw_pressure, 4)))

    def is_preemption_active(self) -> bool:
        """
        Returns True if cashier checkout events require immediate background yield.
        "Billing Always Wins" threshold: Active scan burst > 2.0 items/sec or terminal busy.
        """
        scan_rate = self.get_scan_rate()
        with self._lock:
            return scan_rate >= 2.0 or self._payment_terminal_busy or self._active_transactions > 0

    def sample_state(self) -> dict:
        """Returns snapshot of checkout state."""
        return {
            "active_transactions": self._active_transactions,
            "scan_rate_hz": self.get_scan_rate(),
            "payment_terminal_busy": self._payment_terminal_busy,
            "checkout_pressure_index": self.get_checkout_pressure_index(),
            "preemption_engaged": self.is_preemption_active()
        }

pos_monitor = POSMonitor()

