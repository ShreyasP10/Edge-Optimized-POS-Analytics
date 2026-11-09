import os
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Settings:
    # Terminal Identification
    STORE_ID: str = os.getenv("STORE_ID", "ST-0991")
    TERMINAL_ID: str = os.getenv("TERMINAL_ID", "POS-REG-01")
    TERMINAL_TOKEN: str = os.getenv("TERMINAL_TOKEN", "test-edge-token-0991")

    # Networking & Endpoints
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    METRICS_PORT: int = int(os.getenv("METRICS_PORT", "9090"))

    # Hardware & APU Parameters
    VRAM_TOTAL_MB: float = float(os.getenv("VRAM_TOTAL_MB", "4096.0"))
    KAN_DECISION_THRESHOLD: float = float(os.getenv("KAN_DECISION_THRESHOLD", "0.50"))
    MAX_INFERENCE_THREADS: int = int(os.getenv("MAX_INFERENCE_THREADS", "2"))
    DEVICE_ID: int = int(os.getenv("DEVICE_ID", "0"))

    # File Storage Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    KAN_MODEL_PATH: str = os.getenv("KAN_MODEL_PATH", str(BASE_DIR / "models" / "kan_gate_weights.pt"))
    ONNX_MODEL_PATH: str = os.getenv("ONNX_MODEL_PATH", str(BASE_DIR / "models" / "footfall_quant_int8.onnx"))
    SQLITE_DB_PATH: str = os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "data" / "edge_analytics.db"))

    # Cloud Fallback Parameters
    CLOUD_FALLBACK_URL: str = os.getenv("CLOUD_FALLBACK_URL", "https://cloud-gpu.pos-analytics.internal/api/v1/infer")
    CLOUD_FALLBACK_TIMEOUT_MS: int = int(os.getenv("CLOUD_FALLBACK_TIMEOUT_MS", "2000"))
    CLOUD_COST_PER_INFER_USD: float = 0.000450

    # Synchronization
    CLOUD_SYNC_ENABLED: bool = os.getenv("CLOUD_SYNC_ENABLED", "true").lower() == "true"
    CLOUD_SYNC_INTERVAL_SEC: int = int(os.getenv("CLOUD_SYNC_INTERVAL_SEC", "60"))

settings = Settings()

