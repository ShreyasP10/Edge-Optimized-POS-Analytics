# Development Plan & Engineering Roadmap
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Methodology:** Agile / 2-Week Sprint Cadence  
**Target Release:** v1.0 Production Readiness  

---

## 1. Project Objectives & Engineering Strategy

The objective of the development plan is to build, validate, and harden the KAN-Edge POS Analytics software stack to run background artificial intelligence on retail checkout hardware with **zero performance degradation on POS billing**.

### 1.1 Guiding Principles
1. **Safety First ("Billing Always Wins"):** Every architectural component is designed with an emergency hardware preemption circuit breaker.
2. **Interpretability by Design:** No black-box routing. The KAN network must generate mathematically auditable equations for every offloaded dollar.
3. **Hardware-Centric Validation:** Continuous testing on physical AMD Ryzen/Radeon APU checkout terminals under simulated 10-scans/sec grocery checkout bursts.

---

## 2. Work Breakdown Structure (WBS) & Sprint Schedule

```
+----------------------------------------------------------------------------------------------------+
|                                    5-SPRINT DEVELOPMENT TIMELINE                                   |
+----------+-------------------------------------------------------------+--------------------------+
| SPRINT   | FOCUS & CORE DELIVERABLES                                   | TARGET COMPLETION        |
+----------+-------------------------------------------------------------+--------------------------+
| Sprint 1 | Hardware Telemetry Hooks & POS Checkout Simulation Harness  | End of Week 2            |
| Sprint 2 | Kolmogorov-Arnold Network (KAN) Router & Symbolic Extraction| End of Week 4            |
| Sprint 3 | ONNX DirectML / Vulkan Inference Worker & Quantization      | End of Week 6            |
| Sprint 4 | Zero-Copy Cloud Fallback Client & Resilient SQLite Sync     | End of Week 8            |
| Sprint 5 | K3s Host Isolation, POS Benchmarking & Production Rollout   | End of Week 10           |
+----------+-------------------------------------------------------------+--------------------------+
```

---

## 3. Detailed Sprint Backlog & Deliverables

### Sprint 1: Telemetry Observation & Checkout Simulation Harness
* **Goal:** Create non-blocking hardware sampling and a synthetic POS billing load generator.
* **Tasks:**
  * [x] **TSK-101:** Implement `HardwareObserver` reading free shared APU memory via DirectX DXGI (Windows) and `sysfs` (Linux).
  * [x] **TSK-102:** Implement `POSCheckoutMonitor` intercepting keyboard/scanner events and calculating the 5-second moving average scan rate.
  * [x] **TSK-103:** Develop `POSBillingSimulator` GUI generating bursty cashier item scans (1 to 10 items/sec) to stress-test the terminal.
  * [x] **TSK-104:** Create unit test suite verifying telemetry polling overhead stays below $0.1\%$ CPU utilization.
* **Exit Criteria:** Telemetry module updates in-memory state vector $\mathbf{x}$ every 100ms with zero measurable jitter on the billing simulator.

---

### Sprint 2: KAN Gating Engine & Symbolic Extraction Pipeline
* **Goal:** Build the dynamic routing engine using `pykan` and verify symbolic formula generation.
* **Tasks:**
  * [x] **TSK-201:** Design 5-input, 3-hidden, 1-output KAN architecture in PyTorch (`width=[5, 3, 1], grid=5, k=3`).
  * [x] **TSK-202:** Implement multi-objective training script (`scripts/train_kan_gate.py`) with exponential penalty for billing interference.
  * [x] **TSK-203:** Implement automated B-spline pruning and symbolic regression formula extractor emitting human-readable equations.
  * [x] **TSK-204:** Build FastAPI routing endpoint (`POST /api/v1/tasks/analyze`) that scores tasks in $< 3.5\text{ms}$.
* **Exit Criteria:** KAN Gate correctly classifies 100% of high-queue states ($Q_{\text{len}} \ge 0.8$) as `CLOUD_GPU` and outputs a symbolic formula string.

---

### Sprint 3: DirectML / Vulkan Inference Worker & INT8 Quantization
* **Goal:** Execute quantized vision models on AMD Radeon iGPU with hardware preemption.
* **Tasks:**
  * [x] **TSK-301:** Set up ONNX Runtime with `DmlExecutionProvider` (Windows) and `VulkanExecutionProvider` (Linux).
  * [x] **TSK-302:** Quantize YOLOv8-nano footfall model to INT8 using symmetric per-channel calibration.
  * [x] **TSK-303:** Implement DirectML session manager with clamped thread pool ($T \le 2$) and memory pattern tuning.
  * [x] **TSK-304:** Implement emergency preemption hook: abort active frame inference and yield GPU context in $< 5\text{ms}$ upon POS scan signal.
* **Exit Criteria:** Model runs on AMD Vega 8 iGPU in $< 120\text{ms}$ per frame with zero screen flicker or cashier UI stutter.

---

### Sprint 4: Zero-Copy Cloud Fallback & Resilient Data Sync
* **Goal:** Implement seamless cloud offloading and offline-first database synchronization.
* **Tasks:**
  * [x] **TSK-401:** Implement memory-mapped shared buffer (`/dev/shm`) for zero-copy payload streaming.
  * [x] **TSK-402:** Build asynchronous gRPC fallback client with TLS 1.3 and Snappy compression.
  * [x] **TSK-403:** Configure local SQLite database with `PRAGMA journal_mode=WAL` for non-blocking telemetry logging.
  * [x] **TSK-404:** Implement background sync daemon replicating batches of 100 records to central PostgreSQL in the cloud.
* **Exit Criteria:** Seamless failover to AWS GPU endpoint during simulated checkout waves; 100% of offline records synced after WAN restoration.

---

### Sprint 5: K3s Host Isolation, POS Benchmarking & Hardening
* **Goal:** Package system into K3s container with OS cgroups v2 resource limits and run 72-hour soak tests.
* **Tasks:**
  * [x] **TSK-501:** Author K3s deployment manifests with `PriorityClass: low-priority-analytics` and hard CPU/RAM limits.
  * [x] **TSK-502:** Configure OS CPU affinity pinning (POS Billing on Cores 0-1, Analytics on Cores 2-3).
  * [x] **TSK-503:** Implement Prometheus `/metrics` exporter tracking iGPU VRAM, temperatures, and KAN decisions.
  * [x] **TSK-504:** Execute 72-hour endurance test on physical AMD Ryzen Embedded POS hardware under 35°C ambient temperatures.
* **Exit Criteria:** Zero POS crashes, 0.00ms billing latency delta, and $> 70\%$ cloud compute cost reduction confirmed over 72 hours.

---

## 4. Hardware Lab Testing Environment

```
+----------------------------------------------------------------------------------------------------+
|                                    HARDWARE LAB TEST RIG                                           |
+---------------------+------------------------------------------------------------------------------+
| POS Terminal        | HP Engage One / Elo TouchPOS with AMD Ryzen Embedded V1605B APU              |
| iGPU & Memory       | AMD Radeon Vega 8 Graphics (8 CUs, 512 SPs), 16 GB DDR4-3200 (Dual Channel)  |
| Operating System    | Windows 10 IoT Enterprise LTSC / Ubuntu 22.04 LTS (Kernel 5.15)              |
| Barcode Scanner     | Zebra DS2208 USB Barcode Scanner (Simulating 10 scans/sec barcode burst)     |
| Payment Terminal    | Verifone / Ingenico EMV PIN Pad (Simulating active chip authorization)       |
| Ingestion Camera    | 1080p 30fps USB UVC Overhead Camera (Footfall video stream)                  |
| Cloud Mock Target   | AWS EC2 g4dn.xlarge (NVIDIA T4 16GB) running mock inference backend          |
+---------------------+------------------------------------------------------------------------------+
```

