import time
from typing import Dict, Any
from src.config import settings
from src.resilience.circuit_breaker import cloud_gpu_circuit_breaker, CircuitBreakerOpenException
from src.resilience.retry_policy import execute_with_retry
from src.resilience.kill_switches import kill_switch_manager

class CloudFallbackClient:
    """
    Resilient cloud fallback client.
    Protected by:
    1. Circuit Breaker (Fast-fail if cloud GPU cluster is degraded)
    2. Exponential Backoff with Full Jitter
    3. Kill Switch override (KILL_CLOUD_FALLBACK)
    4. Cached fallback responses during network isolation
    """

    def __init__(self, fallback_url: str = None, cost_per_infer: float = None):
        self.fallback_url = fallback_url or settings.CLOUD_FALLBACK_URL
        self.cost_per_infer = cost_per_infer or settings.CLOUD_COST_PER_INFER_USD

    def _execute_network_call(self, task_type: str, payload_size_mb: float) -> Dict[str, Any]:
        """Simulates or performs raw network transmission to cloud cluster."""
        # Simulated cloud round-trip latency (network WAN + NVIDIA A10G execution)
        simulated_latency = 0.040 + (payload_size_mb * 0.002)
        time.sleep(min(0.200, simulated_latency))
        return {
            "routing": "CLOUD_GPU",
            "cloud_transfer_ms": round(simulated_latency * 400, 2),
            "cloud_inference_ms": round(simulated_latency * 600, 2),
            "total_cloud_ms": round(simulated_latency * 1000, 2),
            "incurred_cost_usd": self.cost_per_infer,
            "result": {
                "footfall_delta": 4,
                "current_occupancy": 22,
                "cloud_worker_id": "aws-g4dn-worker-pod-07",
                "cached": False
            }
        }

    def _cached_degraded_fallback(self, task_type: str, payload_size_mb: float) -> Dict[str, Any]:
        """Executed when the circuit breaker is OPEN or cloud is killed."""
        fallback_data = kill_switch_manager.get_cached_fallback(task_type)
        return {
            "routing": "CLOUD_GPU_CACHED_FALLBACK",
            "cloud_transfer_ms": 0.0,
            "cloud_inference_ms": 0.0,
            "total_cloud_ms": 1.2,
            "incurred_cost_usd": 0.000000,  # Zero cloud spend incurred when cached!
            "result": {
                **fallback_data,
                "circuit_breaker": "OPEN",
                "degradation_mode": "ACTIVE"
            }
        }

    def offload_task(self, task_type: str, payload_size_mb: float) -> Dict[str, Any]:
        """
        Executes cloud offload wrapped in circuit breaker, retries with jitter, and fallback.
        """
        # Kill switch check
        if kill_switch_manager.is_active("KILL_CLOUD_FALLBACK"):
            return self._cached_degraded_fallback(task_type, payload_size_mb)

        def call_with_retries():
            return execute_with_retry(
                func=lambda: self._execute_network_call(task_type, payload_size_mb),
                max_retries=2,
                base_delay_sec=0.05,
                max_delay_sec=0.5
            )

        # Wrap in Circuit Breaker
        return cloud_gpu_circuit_breaker.call(
            func=call_with_retries,
            fallback=lambda: self._cached_degraded_fallback(task_type, payload_size_mb)
        )

cloud_fallback_client = CloudFallbackClient()
