import time
from typing import Dict, Any
from src.config import settings

class CloudFallbackClient:
    """
    Manages zero-copy offloading to elastic AWS/GCP cloud GPUs when local POS
    terminal capacity is constrained or when cashier checkout bursts are active.
    """

    def __init__(self, fallback_url: str = None, cost_per_infer: float = None):
        self.fallback_url = fallback_url or settings.CLOUD_FALLBACK_URL
        self.cost_per_infer = cost_per_infer or settings.CLOUD_COST_PER_INFER_USD

    def offload_task(self, task_type: str, payload_size_mb: float) -> Dict[str, Any]:
        """
        Transmits payload metadata/tensor to remote cloud GPU cluster.
        In production, streams via gRPC over TLS 1.3.
        """
        t0 = time.perf_counter()

        # Simulated cloud round-trip latency (network WAN + NVIDIA A10G execution)
        simulated_latency = 0.045 + (payload_size_mb * 0.002)
        time.sleep(min(0.200, simulated_latency))

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        return {
            "routing": "CLOUD_GPU",
            "cloud_transfer_ms": round(elapsed_ms * 0.4, 2),
            "cloud_inference_ms": round(elapsed_ms * 0.6, 2),
            "total_cloud_ms": elapsed_ms,
            "incurred_cost_usd": self.cost_per_infer,
            "result": {
                "footfall_delta": 4,
                "current_occupancy": 22,
                "cloud_worker_id": "aws-g4dn-worker-pod-07"
            }
        }

cloud_fallback_client = CloudFallbackClient()

