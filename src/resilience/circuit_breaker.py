import time
import threading
from enum import Enum
from typing import Callable, Any, Optional

class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation: traffic flows to target
    OPEN = "OPEN"            # Tripped: fast-fail immediately, traffic diverted to fallback
    HALF_OPEN = "HALF_OPEN"  # Testing: allowing limited trial requests to check recovery

class CircuitBreakerOpenException(Exception):
    """Raised when an operation is attempted while the circuit breaker is OPEN."""
    pass

class CircuitBreaker:
    """
    Thread-safe state-machine Circuit Breaker protecting upstream dependencies
    (e.g., Cloud GPU fallback, central PostgreSQL sync, camera streaming).
    Prevents cascading failure and resources exhaustion during outages.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout_sec: float = 15.0,
        half_open_success_threshold: int = 2
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.half_open_success_threshold = half_open_success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_state_change = time.time()
        self._last_failure_time = 0.0
        self._total_tripped_count = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                if time.time() - self._last_state_change >= self.recovery_timeout_sec:
                    self._state = CircuitState.HALF_OPEN
                    self._last_state_change = time.time()
                    self._success_count = 0
            return self._state

    def call(self, func: Callable, *args, fallback: Optional[Callable] = None, **kwargs) -> Any:
        """
        Executes the function if circuit is closed or half-open.
        If open or execution fails, triggers fallback or raises CircuitBreakerOpenException.
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            if fallback is not None:
                return fallback(*args, **kwargs)
            raise CircuitBreakerOpenException(
                f"Circuit breaker '{self.name}' is OPEN. Fast-failing upstream call."
            )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            if fallback is not None:
                return fallback(*args, **kwargs)
            raise

    def _on_success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._last_state_change = time.time()
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def _on_failure(self, error: Exception):
        with self._lock:
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                # Immediate trip back to OPEN if a trial fails
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
                self._total_tripped_count += 1
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._last_state_change = time.time()
                    self._total_tripped_count += 1

    def force_state(self, state: CircuitState):
        """Administrative override."""
        with self._lock:
            self._state = state
            self._last_state_change = time.time()
            if state == CircuitState.CLOSED:
                self._failure_count = 0
                self._success_count = 0

    def get_status(self) -> dict:
        """Returns circuit breaker diagnostics."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "success_count": self._success_count,
                "recovery_timeout_sec": self.recovery_timeout_sec,
                "seconds_in_current_state": round(time.time() - self._last_state_change, 1),
                "total_tripped_count": self._total_tripped_count
            }

# Pre-configured circuit breakers for the core subsystems
cloud_gpu_circuit_breaker = CircuitBreaker("cloud_gpu_fallback", failure_threshold=3, recovery_timeout_sec=15.0)
postgres_sync_circuit_breaker = CircuitBreaker("postgres_cloud_sync", failure_threshold=5, recovery_timeout_sec=30.0)
camera_ingest_circuit_breaker = CircuitBreaker("camera_frame_ingest", failure_threshold=4, recovery_timeout_sec=10.0)
