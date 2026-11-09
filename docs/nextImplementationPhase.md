# Next Implementation Phase: Production Scaffolding & Hardware Validation
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Phase:** Transition from Design/Specification to Code Scaffolding & Edge Integration  

---

## 1. Executive Summary & Phase Objectives

With the complete specification suite approved, the **Next Implementation Phase** focuses on delivering the production-ready code scaffolding, hardware-native drivers, and physical terminal integration.

### Core Objectives:
1. **Scaffold the Python/FastAPI Edge Application Structure:** Implement the clean modular codebase (`src.telemetry`, `src.router`, `src.inference`, `src.storage`).
2. **Implement AMD Vega Hardware Telemetry Hooks:** Direct DirectX 12 DXGI and Linux DRM sysfs bindings.
3. **Train the Baseline KAN Gating Model:** Train B-spline coefficients on simulated POS checkout curves.
4. **Deploy ONNX DirectML Runtime on Physical APU Hardware:** Validate quantized INT8 person detection without POS billing screen stutter.

---

## 2. Target Repository Scaffolding

The codebase will be organized into the following production structure:

```
edge-pos-analytics/
├── .env.example
├── docker-compose.yml
├── Dockerfile.edge
├── requirements.txt
├── README.md
├── docs/                             # Full architectural specification suite
│   ├── PRD.md
│   ├── TRD.md
│   ├── ARCHITECTURE.md
│   ├── KAN_ROUTING_SPEC.md
│   ├── AMD_VEGA_OPTIMIZATION.md
│   ├── DEPLOYMENT_GUIDE.md
│   ├── SECURITY_PRIVACY.md
│   ├── API_REFERENCE.md
│   ├── SRD.md
│   ├── SRS.md
│   ├── DEV_PLAN.md
│   ├── nextImplementationPhase.md
│   ├── REVIEW.md
│   ├── REVIEW_v4.md
│   ├── IMPROVEMENTS.md
│   ├── RISK_REGISTER.md
│   └── INDEX.md
├── k8s/                              # Kubernetes manifests
│   ├── priority-classes.yaml
│   └── edge-analytics-deployment.yaml
├── scripts/
│   ├── train_kan_gate.py             # pykan training & symbolic extraction script
│   ├── quantize_onnx_model.py        # INT8 post-training quantization pipeline
│   └── pos_billing_stress_test.py    # POS cashier barcode scan generator
└── src/
    ├── __init__.py
    ├── main.py                       # FastAPI entry point & lifespan events
    ├── config.py                     # Environment variables & hardware profiles
    ├── telemetry/
    │   ├── __init__.py
    │   ├── hardware_observer.py      # DirectML/DXGI & sysfs memory poller
    │   └── pos_monitor.py            # Checkout queue depth & scanner hook
    ├── router/
    │   ├── __init__.py
    │   ├── kan_gate.py               # pykan forward inference & symbolic evaluator
    │   └── preemption.py             # Billing supremacy fast-circuit breaker
    ├── inference/
    │   ├── __init__.py
    │   ├── onnx_engine.py            # DirectML / Vulkan INT8 execution session
    │   └── preprocessor.py           # In-memory zero-copy tensor formatting
    ├── fallback/
    │   ├── __init__.py
    │   └── cloud_client.py           # Asynchronous gRPC fallback streamer
    └── storage/
        ├── __init__.py
        ├── sqlite_store.py           # SQLite WAL persistence engine
        └── sync_daemon.py            # Asynchronous PostgreSQL cloud replication
```

---

## 3. Immediate Implementation Tickets (Sprint Execution Backlog)

### Ticket 1: Hardware Telemetry Observer (`src/telemetry/hardware_observer.py`)
* **Task:** Implement cross-platform hardware monitoring for Windows (DXGI / DirectML memory query) and Linux (`/sys/class/drm/card0/device/mem_info_vram_used`).
* **Input:** System hardware polling loop running every 250ms.
* **Output:** Normalized telemetry tuple: `(vram_free_ratio, apu_temp_ratio, memory_pressure_flag)`.
* **Acceptance Criteria:** Polling consumes $< 0.1\%$ CPU on a 4-core AMD Ryzen Embedded APU.

### Ticket 2: POS Queue & Barcode Hook (`src/telemetry/pos_monitor.py`)
* **Task:** Capture keyboard/scanner events or POS transaction state flags.
* **Logic:** Calculate 5-second exponential moving average of scans/second. If cashier scans $> 1$ item/sec, set `billing_active = True`.
* **Acceptance Criteria:** Signal propagation latency from barcode scan to KAN preemption flag $< 2.0\text{ ms}$.

### Ticket 3: KAN Gating Model & Training Script (`scripts/train_kan_gate.py`)
* **Task:** Implement `KAN(width=[5, 3, 1], grid=5, k=3)` using `pykan`. Train on synthetic store profiles with high penalty for checkout interference.
* **Output:** Saved PyTorch weights (`models/kan_gate_weights.pt`) and exported symbolic equation text string.
* **Acceptance Criteria:** Model evaluates forward pass in $< 3.5\text{ ms}$ on a single CPU thread.

### Ticket 4: ONNX DirectML Runtime Session (`src/inference/onnx_engine.py`)
* **Task:** Initialize `InferenceSession` with `DmlExecutionProvider` targeting AMD Radeon Vega iGPU (`device_id=0`).
* **Settings:** Thread pool clamped to 2 threads; memory pattern optimization disabled to prevent VRAM lockup.
* **Acceptance Criteria:** Quantized YOLOv8-nano inference completes in $< 120\text{ ms}$ on AMD Vega 8 iGPU.

### Ticket 5: FastAPI Ingestion Route (`src/main.py`)
* **Task:** Implement `POST /api/v1/tasks/analyze` accepting payload metadata, querying telemetry, executing KAN routing, and dispatching to local ONNX or cloud fallback.
* **Acceptance Criteria:** API returns HTTP 200 with `routing`, `kan_score`, and `kan_justification` algebraic formula.

---

## 4. Hardware Verification Protocol (How to Run on Physical Hardware)

To verify the software on physical AMD Ryzen/Radeon POS hardware:

```bash
# 1. Clone repository to POS terminal
git clone https://github.com/your-org/edge-pos-analytics.git
cd edge-pos-analytics

# 2. Set up Python environment
python -m venv venv
source venv/bin/activate  # Or .\venv\Scripts\Activate.ps1 on Windows

# 3. Install core dependencies
pip install -r requirements.txt

# 4. Train and calibrate the KAN gate for the local APU
python -m scripts.train_kan_gate --vram-total-mb 4096 --extract-symbolic True

# 5. Launch the Edge Analytics Engine
uvicorn src.main:app --host 127.0.0.1 --port 8000 --workers 1

# 6. In a secondary terminal, launch the POS Billing Stress Simulator
python -m scripts.pos_billing_stress_test --scans-per-sec 6

# 7. Submit test analytics tasks and verify KAN preemption
curl -X POST http://127.0.0.1:8000/api/v1/tasks/analyze \
  -H "Content-Type: application/json" \
  -d '{"task_type": "footfall_estimation", "payload_size_mb": 15, "latency_bound_ms": 500, "store_id": "ST-0991"}'
```
* **Expected Result:** During the scan burst, KAN immediately offloads tasks to `CLOUD_GPU` with justification formula indicating high checkout queue pressure, while the POS checkout simulator registers $0.00\text{ ms}$ jitter.

