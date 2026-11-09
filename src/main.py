import uuid
import time
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header, Response
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

from src.config import settings
from src.telemetry.hardware_observer import hardware_observer
from src.telemetry.pos_monitor import pos_monitor
from src.router.kan_gate import kan_gate
from src.inference.onnx_engine import onnx_engine
from src.fallback.cloud_client import cloud_fallback_client
from src.storage.sqlite_store import sqlite_store
from src.storage.sync_daemon import sync_daemon

# --- Prometheus Observability Metrics ---
METRIC_KAN_ROUTING = Counter(
    "kan_routing_decision_total",
    "Total task routing decisions made by KAN gate",
    ["decision"]
)
METRIC_CLOUD_COST = Counter(
    "kan_cloud_offload_cost_usd_total",
    "Cumulative cloud GPU offloading costs incurred"
)
METRIC_VRAM_FREE = Gauge(
    "pos_igpu_vram_free_bytes",
    "Available APU shared VRAM in bytes"
)
METRIC_SCAN_RATE = Gauge(
    "pos_checkout_scanner_rate_hz",
    "Rolling barcode scanner frequency in Hz"
)
METRIC_ACTIVE_TX = Gauge(
    "pos_checkout_active_transactions",
    "Active customer transactions at checkout"
)

# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_daemon.start()
    yield
    sync_daemon.stop()

app = FastAPI(
    title="KAN-Edge POS Analytics Engine",
    description="Intelligent edge-cloud load balancer using Kolmogorov-Arnold Networks (KAN) for retail POS terminals.",
    version="1.0.0",
    lifespan=lifespan
)

# --- Pydantic Request/Response Models ---
class TaskRequest(BaseModel):
    task_type: str = Field(default="footfall_estimation", description="Analytics task type")
    payload_size_mb: float = Field(default=12.0, ge=0.1, le=200.0, description="Payload tensor size in MB")
    latency_bound_ms: int = Field(default=500, ge=50, le=5000, description="Latency SLA in ms")
    store_id: str = Field(default="ST-0991")
    terminal_id: Optional[str] = Field(default="POS-REG-01")
    payload_ref: Optional[str] = Field(default=None)

class SimulateScanRequest(BaseModel):
    burst_count: int = Field(default=1, ge=1, le=50, description="Simulated item scan pulses")

# --- API Endpoints ---

@app.get("/healthz")
def healthz():
    """Liveness probe."""
    return {"status": "HEALTHY", "node": settings.TERMINAL_ID, "store": settings.STORE_ID}

@app.get("/metrics")
def metrics():
    """Prometheus metrics scrape endpoint."""
    hw = hardware_observer.get_vram_metrics()
    pos = pos_monitor.sample_state()
    METRIC_VRAM_FREE.set(hw["vram_free_mb"] * 1024 * 1024)
    METRIC_SCAN_RATE.set(pos["scan_rate_hz"])
    METRIC_ACTIVE_TX.set(pos["active_transactions"])
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/api/v1/telemetry/live")
def get_live_telemetry():
    """Returns real-time hardware APU load and POS billing queue state."""
    hw = hardware_observer.sample_state()
    pos = pos_monitor.sample_state()
    return {
        "timestamp": time.time(),
        "store_id": settings.STORE_ID,
        "terminal_id": settings.TERMINAL_ID,
        "hardware": hw,
        "pos_billing": pos
    }

@app.post("/api/v1/telemetry/simulate_scan")
def simulate_scan(req: SimulateScanRequest):
    """
    Simulates cashier barcode scan bursts.
    Used to test the 'Billing Always Wins' preemption circuit breaker.
    """
    for _ in range(req.burst_count):
        pos_monitor.record_scan_event()
    return {
        "status": "SCANS_RECORDED",
        "burst_count": req.burst_count,
        "new_scan_rate_hz": pos_monitor.get_scan_rate(),
        "preemption_active": pos_monitor.is_preemption_active()
    }

@app.post("/api/v1/tasks/analyze")
def analyze_task(req: TaskRequest, x_terminal_token: Optional[str] = Header(None)):
    """
    Core Entry Point:
    1. Intercepts incoming analytics task.
    2. Evaluates KAN B-spline gating layer.
    3. Dispatches to local AMD Radeon iGPU or AWS/GCP Cloud Fallback.
    4. Records mathematical audit log in SQLite.
    """
    task_id = str(uuid.uuid4())
    t0 = time.perf_counter()

    # Step 1: KAN Gating Evaluation
    evaluation = kan_gate.evaluate(
        payload_size_mb=req.payload_size_mb,
        latency_bound_ms=req.latency_bound_ms
    )
    routing = evaluation["routing"]
    METRIC_KAN_ROUTING.labels(decision=routing).inc()

    # Step 2: Route Execution
    if routing == "LOCAL_IGPU":
        inference_out = onnx_engine.run_inference(req.task_type, req.payload_size_mb)
        if inference_out.get("aborted", False):
            # Preempted mid-execution by a cashier scan burst: Offload to cloud instantly!
            cloud_out = cloud_fallback_client.offload_task(req.task_type, req.payload_size_mb)
            routing = "CLOUD_GPU_PREEMPTED"
            incurred_cost = settings.CLOUD_COST_PER_INFER_USD
            exec_time_ms = cloud_out["total_cloud_ms"]
            result = cloud_out["result"]
            METRIC_CLOUD_COST.inc(incurred_cost)
        else:
            incurred_cost = 0.000000
            exec_time_ms = inference_out["inference_time_ms"]
            result = {
                "footfall_delta": inference_out["footfall_count"],
                "current_occupancy": 18,
                "detections": inference_out["detections"]
            }
    else:
        # Offload to Cloud GPU Cluster
        cloud_out = cloud_fallback_client.offload_task(req.task_type, req.payload_size_mb)
        incurred_cost = settings.CLOUD_COST_PER_INFER_USD
        exec_time_ms = cloud_out["total_cloud_ms"]
        result = cloud_out["result"]
        METRIC_CLOUD_COST.inc(incurred_cost)

    total_duration_ms = round((time.perf_counter() - t0) * 1000, 2)

    # Step 3: Record to Local SQLite Audit Ledger
    sqlite_store.record_event(
        event_id=task_id,
        task_type=req.task_type,
        routing_decision=routing,
        kan_score=evaluation["kan_score"],
        kan_formula=evaluation["justification"],
        payload_size_mb=req.payload_size_mb,
        execution_time_ms=total_duration_ms,
        incurred_cost_usd=incurred_cost,
        telemetry_snapshot=evaluation["telemetry_snapshot"]
    )

    return {
        "task_id": task_id,
        "status": "COMPLETED",
        "routing": routing,
        "kan_evaluation": {
            "score": evaluation["kan_score"],
            "decision_threshold": evaluation["decision_threshold"],
            "justification": evaluation["justification"],
            "preemption_triggered": evaluation["preemption_triggered"],
            "override_reason": evaluation["override_reason"]
        },
        "execution_metrics": {
            "routing_time_ms": evaluation["routing_time_ms"],
            "execution_time_ms": exec_time_ms,
            "total_time_ms": total_duration_ms,
            "incurred_cost_usd": incurred_cost
        },
        "result": result
    }

@app.get("/api/v1/audit/logs")
def get_audit_logs(limit: int = 50, offset: int = 0):
    """Fetches local SQLite audit ledger records containing KAN symbolic formulas."""
    logs = sqlite_store.query_audit_logs(limit=limit, offset=offset)
    return {
        "limit": limit,
        "offset": offset,
        "record_count": len(logs),
        "records": logs
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, log_level="info")

