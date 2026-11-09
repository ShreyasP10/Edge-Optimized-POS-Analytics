import time
from src.telemetry.pos_monitor import pos_monitor

class PreemptionManager:
    """
    Guarantees the core operational axiom: 'Billing Always Wins'.
    Acts as an emergency circuit breaker that commands the local inference worker
    to yield the GPU context in < 5ms if a cashier scan burst is registered.
    """

    def __init__(self, latency_threshold_ms: float = 5.0):
        self.latency_threshold_ms = latency_threshold_ms

    def should_abort_local_inference(self) -> bool:
        """
        Queried by the ONNX inference worker between operator executions or sub-batches.
        If active cashier scans spike, immediately signals abort.
        """
        return pos_monitor.is_preemption_active()

preemption_manager = PreemptionManager()

