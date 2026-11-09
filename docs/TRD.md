# Technical Requirements Document (TRD)
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Status:** Approved / Engineering Specification  
**Target Release:** v1.0-GA  

---

## 1. System Architecture Overview

The KAN-Edge POS Analytics system is a hybrid edge-cloud machine learning platform designed to safely execute computer vision and predictive analytics on standard Point-of-Sale (POS) terminals without jeopardizing mission-critical checkout software.

```
+----------------------------------------------------------------------------------------------------+
|                                    POS TERMINAL (EDGE NODE)                                        |
|                                                                                                    |
|  +-------------------------------------+         +----------------------------------------------+  |
|  |     POS BILLING SOFTWARE (CDE)      |         |            TELEMETRY OBSERVER                |  |
|  |  - Barcode Scanner / Payment App    |         |  - Windows ETW / Linux procfs Hook           |  |
|  |  - CPU Affinity: Core 0-1 (Pinned)  |         |  - DirectML VRAM & Shared Memory Poller     |  |
|  |  - Priority: HIGH_PRIORITY_CLASS    |         |  - Active Checkout Queue Depth Monitor       |  |
|  +-------------------------------------+         +----------------------------------------------+  |
|                     | (Zero CDE Access)                                 | (Telemetry Feed)         |
|                     x                                                   v                          |
|  +----------------------------------------------------------------------------------------------+  |
|  |                           K3s / SYSTEMD ISOLATION CONTAINER                                  |  |
|  |                                                                                              |  |
|  |   [Task Ingestion: FastAPI]                                                                  |  |
|  |         | (Payload & SLA)                                                                    |  |
|  |         v                                                                                    |  |
|  |   [KAN GATING ENGINE (pykan)] <--- (Telemetry: VRAM, Queue, CPU, Temp)                       |  |
|  |         |                                                                                    |  |
|  |         +--- Score >= 0.50 ----------------------+--- Score < 0.50 (Overload/Spike) ---------+  |
|  |         |                                        |                                           |  |
|  |         v                                        v                                           |  |
|  |   [LOCAL INFERENCE ENGINE]             [ZERO-COPY CLOUD BUFFER]                              |  |
|  |   - ONNX Runtime (DirectML/Vulkan)     - Shared memory ring buffer                           |  |
|  |   - Quantized INT8/FP16 models         - gRPC / HTTP/2 Streamer                              |  |
|  |   - AMD Radeon / Intel iGPU            - Instant bypass on billing spike                     |  |
|  |         |                                        |                                           |  |
|  |         v                                        | (Offload payload)                         |  |
|  |   [LOCAL SQLite STORE (WAL)]                     |                                           |  |
|  |   - Feature & Log persistence                    |                                           |  |
|  |   - Offline resilience buffer                    |                                           |  |
|  +--------------------------------------------------|-------------------------------------------+  |
+-----------------------------------------------------|----------------------------------------------+
                                                      |
                                                      v (mTLS Public / VPN)
                       +---------------------------------------------------------------+
                       |                 CLOUD BACKEND (AWS / GCP)                     |
                       |                                                               |
                       |  +---------------------------+   +-------------------------+  |
                       |  |   CLOUD GPU INFERENCE     |   |   CENTRAL POSTGRESQL    |  |
                       |  |   - NVIDIA T4/A10G Cluster|   |   - Aggregated Analytics|  |
                       |  |   - Multi-Camera Re-ID    |   |   - Audit Ledger Sync   |  |
                       |  +---------------------------+   +-------------------------+  |
                       +---------------------------------------------------------------+
```

---

## 2. Hardware & Operating Environment Specifications

### 2.1 Target Edge POS Hardware Profile
* **Target APU / CPU:**
  * AMD Ryzen Embedded (e.g., V1000/V2000/R1000 series with Radeon Vega/RDNA graphics).
  * AMD Ryzen 3 / 5 / 7 PRO commercial desktop APUs.
  * Intel Core i3 / i5 / i7 (11th Gen+) with Intel Iris Xe Graphics.
* **System RAM:** 8 GB to 16 GB DDR4/DDR5 (Shared unified memory architecture; 1.5 GB to 4.0 GB dynamically allocated to iGPU).
* **Storage:** 128 GB+ NVMe SSD / SATA SSD.
* **Operating Systems Supported:**
  * Windows 10 / 11 IoT Enterprise (64-bit).
  * Ubuntu 22.04 LTS / SUSE Linux Enterprise Server (SLES) for Point of Service.

### 2.2 Host Isolation & OS Tuning
To guarantee the prime directive—**"Billing Always Wins"**—the host operating system must enforce strict CPU, memory, and I/O isolation between the POS Billing process and the background analytics container.

| Resource | POS Billing Application | K3s Analytics Pod / KAN Gate | Enforcement Mechanism |
| :--- | :--- | :--- | :--- |
| **CPU Cores** | Cores 0, 1 (Isolated, pinned) | Cores 2, 3 (Shared, throttled) | `taskset` (Linux) / Processor Affinity Mask (Windows) |
| **CPU Quota** | 100% of Cores 0–1 | $\le 50\%$ of Cores 2–3 | Linux `cpu.cfs_quota_us` / Windows Job Objects |
| **Process Priority**| `HIGH_PRIORITY_CLASS` / `nice -20` | `IDLE_PRIORITY_CLASS` / `nice 19` | OS Scheduler configuration |
| **I/O Priority** | Real-time (`ionice -c 1`) | Idle (`ionice -c 3`) | Linux `ionice` / Windows I/O Priority |
| **OOM Killer Score**| `-1000` (Immune to OOM kill) | `+800` (First to be evicted) | `/proc/[pid]/oom_score_adj` |
| **Shared GPU VRAM** | Full priority on demand | Hard cap at 60% of available VRAM | Driver-level memory allocator policy |

---

## 3. Kolmogorov-Arnold Network (KAN) Gating Engine

### 3.1 Mathematical Formulation
The routing decision is parameterized by a Kolmogorov-Arnold Network (KAN), which replaces fixed activation functions on nodes with learnable univariate B-spline activation functions parameterized along the edges:

$$f(\mathbf{x}) = \sum_{q=1}^{2n+1} \Phi_q \left( \sum_{p=1}^n \phi_{q,p}(x_p) \right)$$

Where:
* $\mathbf{x} = [x_1, x_2, x_3, x_4, x_5]^T$ is the normalized input telemetry vector.
* $\phi_{q,p}$ are univariate B-spline functions:
  $$\phi(x) = c_b b(x) + \sum_i c_i B_i(x)$$
  with $B_i(x)$ being cubic B-spline basis functions.
* $\Phi_q$ is the outer spline aggregation function.

### 3.2 Telemetry Feature Vector ($\mathbf{x}$)
The input vector $\mathbf{x} \in \mathbb{R}^5$ is sampled dynamically every time an inference task is submitted:

1. **$x_1 = V_{\text{avail}}$ (Normalized Available VRAM):**
   $$x_1 = \frac{\text{VRAM}_{\text{free\_mb}}}{\text{VRAM}_{\text{total\_mb}}} \in [0.0, 1.0]$$
2. **$x_2 = Q_{\text{len}}$ (Active Checkout Queue Depth & Event Pressure):**
   $$x_2 = \min\left(1.0, \frac{\text{ActiveTransactions} + 0.5 \times \text{ScansPerSec}}{10}\right) \in [0.0, 1.0]$$
3. **$x_3 = S_{\text{payload}}$ (Payload Input Size):**
   $$x_3 = \frac{\text{PayloadSizeMB}}{50.0} \in [0.0, 1.0]$$
4. **$x_4 = L_{\text{bound}}$ (Latency SLA Strictness):**
   $$x_4 = 1.0 - \min\left(1.0, \frac{\text{LatencyBoundMs}}{1000.0}\right) \in [0.0, 1.0]$$
5. **$x_5 = T_{\text{thermal}}$ (APU Thermal Headroom):**
   $$x_5 = \max\left(0.0, \frac{85.0 - T_{\text{die\_celsius}}}{85.0 - 40.0}\right) \in [0.0, 1.0]$$

### 3.3 Symbolic Regression & Formula Generation
Using `pykan`, the trained network weights are pruned using L1 regularization on spline coefficients and projected into closed-form symbolic expressions using symbolic regression:

```python
# Conceptual extraction workflow using pykan
from kan import KAN
import torch

model = KAN(width=[5, 3, 1], grid=5, k=3, seed=42)
# ... model loaded with pre-calibrated weights ...
symbolic_formula = model.symbolic_formula()[0][0]
```

A representative generated formula evaluated during runtime is:
$$\text{Score}(\mathbf{x}) = 0.85 \cdot x_1 - 1.20 \cdot x_2 - 0.45 \cdot x_3 + 0.30 \cdot x_4 + 0.20 \cdot x_5$$

### 3.4 Decision Boundary & Fast-Bypass Rules
* **Execution Threshold:**
  $$\text{Target} = \begin{cases} \text{LOCAL\_IGPU}, & \text{if } \text{Score} \ge 0.50 \\ \text{CLOUD\_GPU}, & \text{if } \text{Score} < 0.50 \end{cases}$$
* **Hard Emergency Bypass ("Billing Always Wins"):**
  Regardless of KAN output, if the POS telemetry observer detects an active barcode scan burst ($> 3$ items/sec) or credit card authorization in progress, the gate triggers an immediate hard override:
  $$\text{If } Q_{\text{len}} \ge 0.80 \implies \text{Force CLOUD\_GPU or DROP}$$

---

## 4. Local Inference Pipeline (ONNX Runtime)

### 4.1 Execution Providers & Acceleration
* **Windows Host:** ONNX Runtime using `DmlExecutionProvider` (DirectML), allowing low-overhead hardware acceleration over DirectX 12 compute drivers for AMD Radeon and Intel iGPUs.
* **Linux Host:** ONNX Runtime using `VulkanExecutionProvider` or `OpenVINOExecutionProvider` targeting the integrated GPU compute pipeline.
* **Session Configuration:**
  ```python
  import onnxruntime as ort

  opts = ort.SessionOptions()
  opts.enable_mem_pattern = True
  opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
  opts.intra_op_num_threads = 2
  opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

  # DirectML Provider with device_id=0 (iGPU)
  providers = [
      ("DmlExecutionProvider", {"device_id": 0}),
      "CPUExecutionProvider"
  ]
  session = ort.InferenceSession("models/footfall_quant_int8.onnx", opts, providers=providers)
  ```

### 4.2 Model Quantization Standard
* **Models Supported:**
  * YOLOv8-Nano / MobileNetV4 for Person Detection & Footfall Estimation.
  * ResNet-18 (Quantized) for Queue Dwell Time & Aisle Heatmapping.
* **Precision:** INT8 post-training quantization (PTQ) with symmetric per-channel weights and asymmetric per-tensor activations.
* **VRAM Budget:** Maximum model footprint $\le 180\text{MB}$ in shared memory.

---

## 5. Elastic Cloud Fallback Pipeline

### 5.1 Architecture & Transport
* **Zero-Copy Memory Buffer:** Incoming heavy video payloads are held in memory-mapped shared RAM (`/dev/shm` or Windows Named Shared Memory). If offloaded to the cloud, the byte buffer is streamed directly without intermediate serialization.
* **Protocol:** gRPC over HTTP/2 with TLS 1.3 encryption and Snappy compression.
* **Cloud Cluster:** AWS ECS/EKS or GCP GKE running auto-scaling worker pools with NVIDIA T4 or A10G GPUs.

### 5.2 Circuit Breaking & Backpressure
```
+----------------+      Failed (Timeout > 2s)      +--------------------+
|  Cloud Offload | ------------------------------> | Degraded Mode:     |
|  Request       |                                 | - Drop frame batch |
+----------------+                                 | - Log incident     |
        |                                          | - Retain telemetry |
        | Success (< 300ms)                        +--------------------+
        v
+----------------+
| Write Result to|
| SQLite Queue   |
+----------------+
```

---

## 6. Distributed Storage & Data Synchronization

### 6.1 Edge Store: SQLite (WAL Mode)
* **Configuration:**
  * `PRAGMA journal_mode = WAL;` (Concurrent read/write without lock contention).
  * `PRAGMA synchronous = NORMAL;` (Ensures durability against crashes while maximizing write speed).
  * `PRAGMA cache_size = -8000;` (8 MB page cache).
  * `PRAGMA temp_store = MEMORY;`
* **Schema Definition:**
  ```sql
  CREATE TABLE IF NOT EXISTS analytics_events (
      event_id TEXT PRIMARY KEY,
      timestamp INTEGER NOT NULL,
      task_type TEXT NOT NULL,
      routing_decision TEXT NOT NULL,
      kan_score REAL NOT NULL,
      kan_formula TEXT NOT NULL,
      payload_size_bytes INTEGER NOT NULL,
      execution_time_ms REAL NOT NULL,
      incurred_cost_usd REAL NOT NULL,
      features_json TEXT NOT NULL,
      synced INTEGER DEFAULT 0
  );

  CREATE INDEX IF NOT EXISTS idx_events_synced ON analytics_events(synced, timestamp);
  ```

### 6.2 Cloud Synchronization Agent
* An asynchronous background thread reads unsynced rows from SQLite in batches of 100 every 60 seconds.
* Rows are transmitted via HTTPS POST to the Central Cloud PostgreSQL ingest API.
* Upon receiving HTTP 200 with matching event IDs, local rows are marked `synced = 1`.
* A 14-day retention vacuum prunes synced records to maintain edge disk usage below 500 MB.

---

## 7. Observability & Telemetry Specification

### 7.1 Prometheus Metrics Exporter
The edge agent exposes a `/metrics` Prometheus endpoint on `http://127.0.0.1:9090/metrics`:

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `pos_checkout_active_transactions` | Gauge | `store_id`, `terminal_id` | Number of live checkout transactions in progress |
| `pos_checkout_scanner_rate_hz` | Gauge | `terminal_id` | Barcode scan events per second |
| `pos_igpu_vram_free_bytes` | Gauge | `device` | Available shared VRAM on integrated GPU |
| `pos_apu_temperature_celsius` | Gauge | `sensor` | Die temperature of the APU |
| `kan_routing_decision_total` | Counter | `decision` (LOCAL / CLOUD) | Total tasks routed by the KAN gate |
| `kan_routing_duration_seconds` | Histogram | `task_type` | Latency incurred by KAN evaluation (target < 5ms) |
| `kan_cloud_offload_cost_usd_total` | Counter | `store_id` | Cumulative estimated cloud GPU offload cost |
| `edge_sqlite_unsynced_records` | Gauge | `store_id` | Count of pending records awaiting cloud sync |

---

## 8. API Specification

### 8.1 Analytics Ingestion Endpoint
* **Endpoint:** `POST /api/v1/tasks/analyze`
* **Headers:** `Content-Type: application/json`, `X-Terminal-Token: <token>`
* **Request Payload Schema:**
  ```json
  {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AnalyzeTaskRequest",
    "type": "object",
    "properties": {
      "task_type": {
        "type": "string",
        "enum": ["footfall_estimation", "dwell_time", "heatmapping", "re_identification"]
      },
      "payload_size_mb": { "type": "number", "minimum": 0.1 },
      "latency_bound_ms": { "type": "integer", "minimum": 50, "maximum": 5000 },
      "store_id": { "type": "string" },
      "payload_ref": { "type": "string", "description": "Memory-mapped buffer ID or URI" }
    },
    "required": ["task_type", "payload_size_mb", "latency_bound_ms", "store_id"]
  }
  ```

* **Response Payload Schema (200 OK):**
  ```json
  {
    "task_id": "7f3b8c2a-9e12-4d56-b789-0123456789ab",
    "status": "COMPLETED",
    "routing": "LOCAL_IGPU",
    "kan_score": 0.724,
    "kan_justification": "score(0.724) = 0.85 * 0.82(vram) - 1.20 * 0.00(queue) - 0.45 * 0.22(payload) + 0.30 * 0.50(lat)",
    "execution_time_ms": 118.4,
    "incurred_cost_usd": 0.0000,
    "result": {
      "footfall_count": 3,
      "bounding_boxes": [
        {"x1": 120, "y1": 80, "x2": 240, "y2": 320, "confidence": 0.92}
      ]
    }
  }
  ```

### 8.2 Real-Time Telemetry Feed Endpoint
* **Endpoint:** `GET /api/v1/telemetry/live`
* **Protocol:** Server-Sent Events (SSE) or WebSocket
* **Output:** Continuous 1 Hz stream of `{ vram_free_mb, active_tx, apu_temp, last_kan_score }` for on-device diagnostics.

---

## 9. Security, PCI-DSS & Data Minimization Architecture

### 9.1 PCI-DSS Scoping Isolation
1. **Network Demarcation:** The POS Billing application communicates over a PCI-scoped Cardholder Data Environment (CDE) VLAN. The K3s container and analytics worker are bound strictly to an isolated non-CDE subnet or localhost Unix domain socket.
2. **Zero Peripheral Access:** Containers have zero read/write permissions to USB devices handling EMV chip cards, magnetic card swipers, PIN pads, or thermal receipt printers.

### 9.2 Zero Raw Video Egress Guarantee
* Raw video frames captured from security cameras are read into volatile RAM buffers.
* Once the quantized ONNX model extracts vector coordinates (e.g., bounding box centroids $[x, y]$), the raw pixel buffer is zeroed out via `memset`.
* Under no circumstances is raw uncompressed or encoded video written to persistent disk or transmitted across the WAN to the cloud. Only metadata JSON arrays are persisted to SQLite.

