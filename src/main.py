import uuid
import time
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header, Response, Request, status
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

# Resilience & Reliability Modules
from src.resilience.circuit_breaker import (
    cloud_gpu_circuit_breaker,
    postgres_sync_circuit_breaker,
    camera_ingest_circuit_breaker,
    CircuitState
)
from src.resilience.rate_limiter import edge_task_rate_limiter
from src.resilience.kill_switches import kill_switch_manager
from src.resilience.idempotency import idempotency_manager
from src.resilience.load_leveler import queue_load_leveler

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
METRIC_RATE_LIMITED = Counter(
    "resilience_rate_limited_total",
    "Total requests throttled by rate limiter"
)
METRIC_IDEMPOTENT_HITS = Counter(
    "resilience_idempotent_replays_total",
    "Total requests served from idempotency replay cache"
)

# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_daemon.start()
    queue_load_leveler.start()
    yield
    queue_load_leveler.stop()
    sync_daemon.stop()

app = FastAPI(
    title="KAN-Edge POS Analytics Engine (Resilient & Production-Hardened)",
    description="High-reliability, fault-tolerant edge-cloud load balancer using Kolmogorov-Arnold Networks (KAN) for retail POS terminals.",
    version="1.1.0",
    lifespan=lifespan
)

# --- Request / Response Models ---
class TaskRequest(BaseModel):
    task_type: str = Field(default="footfall_estimation", description="Analytics task type")
    payload_size_mb: float = Field(default=12.0, ge=0.1, le=200.0, description="Payload tensor size in MB")
    latency_bound_ms: int = Field(default=500, ge=50, le=5000, description="Latency SLA in ms")
    store_id: str = Field(default="ST-0991")
    terminal_id: Optional[str] = Field(default="POS-REG-01")
    payload_ref: Optional[str] = Field(default=None)
    priority: int = Field(default=2, ge=1, le=3, description="1 (High: Checkout/Theft), 2 (Medium: Footfall), 3 (Low: Heatmap)")

class SimulateScanRequest(BaseModel):
    burst_count: int = Field(default=1, ge=1, le=50, description="Simulated item scan pulses")

class KillSwitchUpdateRequest(BaseModel):
    flag_name: str
    enabled: bool

# --- Health Checks & Graceful Degradation ---

@app.get("/healthz")
@app.get("/healthz/liveness")
def liveness():
    """Liveness probe: verifies process responsiveness."""
    return {"status": "HEALTHY", "node": settings.TERMINAL_ID, "store": settings.STORE_ID}

@app.get("/healthz/readiness")
def readiness():
    """
    Deep Readiness probe:
    - Verifies local SQLite readable & writable (or in read-only mode)
    - Verifies APU shared VRAM is accessible
    - Verifies circuit breaker and queue health
    """
    checks = {}
    is_ready = True

    # 1. Drain Mode check
    if kill_switch_manager.is_active("DRAIN_MODE"):
        return Response(
            content='{"status": "DRAINING", "message": "Terminal is draining for maintenance"}',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json"
        )

    # 2. Database readiness
    try:
        checks["sqlite_unsynced"] = sqlite_store.get_unsynced_count()
        checks["sqlite_status"] = "OK"
    except Exception as e:
        checks["sqlite_status"] = f"ERROR: {str(e)}"
        is_ready = False

    # 3. Hardware telemetry readiness
    try:
        hw = hardware_observer.get_vram_metrics()
        checks["vram_free_ratio"] = hw["vram_free_ratio"]
        checks["hardware_telemetry"] = "OK"
    except Exception as e:
        checks["hardware_telemetry"] = f"ERROR: {str(e)}"
        is_ready = False

    # 4. Circuit Breakers summary
    checks["circuit_breakers"] = {
        "cloud_gpu": cloud_gpu_circuit_breaker.state.value,
        "postgres_sync": postgres_sync_circuit_breaker.state.value
    }

    # 5. Load leveler queue health
    queue_metrics = queue_load_leveler.get_metrics()
    checks["queue_leveler"] = queue_metrics

    response_payload = {
        "status": "READY" if is_ready else "NOT_READY",
        "node": settings.TERMINAL_ID,
        "store": settings.STORE_ID,
        "timestamp": time.time(),
        "read_only_mode": kill_switch_manager.is_active("READ_ONLY_MODE"),
        "checks": checks
    }

    if not is_ready:
        raise HTTPException(status_code=503, detail=response_payload)

    return response_payload

@app.get("/metrics")
def metrics():
    """Prometheus metrics scrape endpoint."""
    hw = hardware_observer.get_vram_metrics()
    pos = pos_monitor.sample_state()
    METRIC_VRAM_FREE.set(hw["vram_free_mb"] * 1024 * 1024)
    METRIC_SCAN_RATE.set(pos["scan_rate_hz"])
    METRIC_ACTIVE_TX.set(pos["active_transactions"])
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

# --- Core Task Ingestion API with Resilience & Idempotency ---

@app.post("/api/v1/tasks/analyze")
def analyze_task(
    req: TaskRequest,
    request: Request,
    response: Response,
    x_terminal_token: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    """
    Core Entry Point with Enterprise Resilience:
    1. Idempotency Key validation (prevents duplicate execution & double billing).
    2. Token-bucket rate limiting per Terminal / API key / IP.
    3. Feature kill switches & graceful degradation (Drain mode, Heavy payload shedding).
    4. KAN Gating evaluation (0.6ms) + 'Billing Always Wins' preemption.
    5. Local quantized inference OR Circuit-breaker protected cloud offload.
    6. Non-blocking SQLite WAL persistence.
    """
    # 1. Drain Mode check
    if kill_switch_manager.is_active("DRAIN_MODE"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Terminal is in DRAIN_MODE for maintenance. Ingestion rejected."
        )

    # 2. Idempotency Key Check
    if idempotency_key:
        status_key, cached_resp = idempotency_manager.get_or_create(idempotency_key)
        if status_key == "HIT":
            METRIC_IDEMPOTENT_HITS.inc()
            response.headers["X-Cache-Lookup"] = "HIT"
            response.headers["X-Idempotent-Replay"] = "true"
            return cached_resp
        elif status_key == "IN_PROGRESS":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task with Idempotency-Key '{idempotency_key}' is currently being processed."
            )

    # 3. Rate Limiting & Quota Check
    client_key = x_terminal_token or (request.client.host if request.client else "local_terminal")
    allowed, rate_info = edge_task_rate_limiter.is_allowed(client_key)
    if not allowed:
        METRIC_RATE_LIMITED.inc()
        response.headers["Retry-After"] = str(rate_info.get("retry_after_sec", 1))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": rate_info["reason"],
                "message": "Terminal analytics quota or rate limit exceeded.",
                "retry_after_sec": rate_info["retry_after_sec"]
            }
        )

    # 4. Heavy Payload Shedding Kill Switch
    if kill_switch_manager.is_active("SHED_HEAVY_PAYLOADS") and req.payload_size_mb > 20.0:
        fallback = kill_switch_manager.get_cached_fallback(req.task_type)
        return {
            "task_id": str(uuid.uuid4()),
            "status": "DEGRADED_LOAD_SHEDDED",
            "routing": "SHEDDED_FALLBACK",
            "reason": "SHED_HEAVY_PAYLOADS_ACTIVE",
            "result": fallback
        }

    task_id = str(uuid.uuid4())
    t0 = time.perf_counter()

    # 5. KAN Gating Evaluation
    evaluation = kan_gate.evaluate(
        payload_size_mb=req.payload_size_mb,
        latency_bound_ms=req.latency_bound_ms
    )
    routing = evaluation["routing"]
    METRIC_KAN_ROUTING.labels(decision=routing).inc()

    # 6. Route Execution with Circuit Breaker Protection
    if routing == "LOCAL_IGPU" and not kill_switch_manager.is_active("KILL_LOCAL_INFERENCE"):
        inference_out = onnx_engine.run_inference(req.task_type, req.payload_size_mb)
        if inference_out.get("aborted", False):
            # Preempted by cashier billing spike: Fallback to Cloud GPU!
            cloud_out = cloud_fallback_client.offload_task(req.task_type, req.payload_size_mb)
            routing = "CLOUD_GPU_PREEMPTED"
            incurred_cost = cloud_out["incurred_cost_usd"]
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
        # Offload to Cloud GPU Cluster (Protected by Circuit Breaker & Retries)
        cloud_out = cloud_fallback_client.offload_task(req.task_type, req.payload_size_mb)
        routing = cloud_out["routing"]
        incurred_cost = cloud_out["incurred_cost_usd"]
        exec_time_ms = cloud_out["total_cloud_ms"]
        result = cloud_out["result"]
        METRIC_CLOUD_COST.inc(incurred_cost)

    total_duration_ms = round((time.perf_counter() - t0) * 1000, 2)

    # 7. Record to Local SQLite Audit Ledger (Honors READ_ONLY_MODE)
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

    final_payload = {
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

    # Complete idempotency record
    if idempotency_key:
        idempotency_manager.complete(idempotency_key, final_payload)
        response.headers["X-Cache-Lookup"] = "MISS"

    return final_payload

# --- Telemetry & Audit Endpoints ---

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

# --- Resilience & Disaster Recovery Administration ---

@app.get("/api/v1/resilience/status")
def get_resilience_status():
    """Returns operational status of all circuit breakers, kill switches, and load queues."""
    return {
        "timestamp": time.time(),
        "circuit_breakers": {
            "cloud_gpu": cloud_gpu_circuit_breaker.get_status(),
            "postgres_sync": postgres_sync_circuit_breaker.get_status(),
            "camera_ingest": camera_ingest_circuit_breaker.get_status()
        },
        "kill_switches": kill_switch_manager.get_all_switches(),
        "load_leveler_queue": queue_load_leveler.get_metrics(),
        "rate_limiter_policy": {
            "rate_per_sec": edge_task_rate_limiter.rate_per_sec,
            "burst_capacity": edge_task_rate_limiter.burst_capacity,
            "daily_quota": edge_task_rate_limiter.daily_quota
        }
    }

@app.post("/api/v1/admin/kill-switches")
def update_kill_switch(req: KillSwitchUpdateRequest):
    """Toggles feature kill switches (READ_ONLY_MODE, DRAIN_MODE, etc.) dynamically."""
    kill_switch_manager.set_switch(req.flag_name, req.enabled)
    return {
        "status": "UPDATED",
        "flag_name": req.flag_name,
        "enabled": req.enabled,
        "current_switches": kill_switch_manager.get_all_switches()
    }

@app.post("/api/v1/admin/circuit-breakers/reset")
def reset_circuit_breaker(name: str = "cloud_gpu_fallback"):
    """Administratively resets a circuit breaker to CLOSED."""
    if name == "cloud_gpu_fallback":
        cloud_gpu_circuit_breaker.force_state(CircuitState.CLOSED)
    elif name == "postgres_cloud_sync":
        postgres_sync_circuit_breaker.force_state(CircuitState.CLOSED)
    return {"status": "RESET", "circuit": name, "new_state": "CLOSED"}

@app.post("/api/v1/admin/backup-drill")
def execute_backup_and_restore_drill():
    """
    Executes a live Online Hot Backup and automated Restore Drill.
    Tests restorability into a sandbox and verifies zero database corruption.
    """
    backup_path, sha256_hash, total_records = sqlite_store.create_online_backup()
    drill_results = sqlite_store.verify_restore_drill(backup_path)
    return {
        "backup_path": backup_path,
        "backup_sha256": sha256_hash,
        "total_records_backed_up": total_records,
        "restore_drill_verification": drill_results
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, log_level="info")
