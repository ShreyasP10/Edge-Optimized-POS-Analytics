# Software Requirements Specification (SRS)
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Standard:** IEEE Std 830-1998 (Recommended Practice for Software Requirements Specifications)  
**Status:** Approved Specification  

---

## 1. Introduction

### 1.1 Purpose
This document specifies the software requirements for the **KAN-Edge POS Analytics** platform. It provides a formal, comprehensive specification for developers, machine learning engineers, quality assurance teams, and system integrators.

### 1.2 Scope
KAN-Edge is a hybrid edge-cloud machine learning runtime deployed on Point-of-Sale (POS) cash registers. It intercepts real-time vision analytics workloads, profiles edge terminal telemetry, evaluates execution viability using a Kolmogorov-Arnold Network (KAN) gating model, and routes execution to either the local AMD/Intel integrated GPU (via ONNX Runtime DirectML/Vulkan) or an elastic cloud GPU cluster.

### 1.3 Definitions, Acronyms, and Abbreviations
* **APU:** Accelerated Processing Unit (AMD CPU + iGPU on single die).
* **CDE:** Cardholder Data Environment (PCI-DSS regulated zone).
* **DirectML:** DirectX Machine Learning API for Windows hardware acceleration.
* **iGPU:** Integrated Graphics Processing Unit.
* **KAN:** Kolmogorov-Arnold Network (Spline-parameterized neural architecture).
* **OOM:** Out of Memory.
* **POS:** Point of Sale.
* **PTQ:** Post-Training Quantization.
* **TDR:** Timeout Detection and Recovery (Windows GPU watchdog).
* **UMA:** Unified Memory Architecture.
* **WAL:** Write-Ahead Logging (SQLite concurrency mode).

---

## 2. Overall Description

### 2.1 Product Perspective
KAN-Edge operates as an unprivileged, low-priority background service co-located on the same physical operating system as the primary POS checkout software. It acts as an autonomous edge compute node within an enterprise retail network.

```
+----------------------------------------------------------------------------------------------------+
|                                      HOST POS OPERATING SYSTEM                                     |
|                                                                                                    |
|  +-------------------------------------+         +----------------------------------------------+  |
|  |     POS BILLING APPLICATION         |         |           KAN-EDGE SOFTWARE STACK            |  |
|  |  - Barcode Scanner / EMV Payment    |         |                                              |  |
|  |  - Real-Time Priority (`nice -20`)  |         |  +----------------------------------------+  |  |
|  |  - High CPU Weight (1000)           |         |  | FastAPI Gateway (:8000)                |  |  |
|  +-------------------------------------+         |  | - Task Ingestion & Pre-validation      |  |  |
|                                                  |  +----------------------------------------+  |  |
|                                                  |                     |                        |  |
|                                                  |  +----------------------------------------+  |  |
|                                                  |  | Hardware Telemetry Observer Daemon     |  |  |
|                                                  |  | - Samples VRAM, Queue, Temp, Scans     |  |  |
|                                                  |  +----------------------------------------+  |  |
|                                                  |                     |                        |  |
|                                                  |  +----------------------------------------+  |  |
|                                                  |  | KAN Gating Engine (pykan)              |  |  |
|                                                  |  | - Evaluates B-splines & emits formula  |  |  |
|                                                  |  +----------------------------------------+  |  |
|                                                  |          | (Local)              | (Cloud)    |  |
|                                                  |          v                      v            |  |
|                                                  |  +----------------+  +--------------------+  |  |
|                                                  |  | ONNX Runtime   |  | Zero-Copy Buffer   |  |  |
|                                                  |  | (DirectML)     |  | & gRPC Streamer    |  |  |
|                                                  |  +----------------+  +--------------------+  |  |
|                                                  |          |                      |            |  |
|                                                  |          +----------+-----------+            |  |
|                                                  |                     v                        |  |
|                                                  |  +----------------------------------------+  |  |
|                                                  |  | Local SQLite Store (WAL) & Cloud Sync  |  |  |
|                                                  |  +----------------------------------------+  |  |
|                                                  +----------------------------------------------+  |
+----------------------------------------------------------------------------------------------------+
```

### 2.2 Product Functions
1. **Hardware & Checkout Telemetry Sampling:** Continuous, non-blocking monitoring of system resources, VRAM headroom, cashier scan rates, and transaction states.
2. **Interpretable Routing Decision:** Multi-variate mathematical scoring using Kolmogorov-Arnold Networks to generate an execution route and a human-readable algebraic formula.
3. **Local Quantized Inference:** Hardware-accelerated execution of INT8/FP16 models on AMD Radeon Vega/RDNA iGPUs.
4. **Elastic Cloud Offload:** Zero-copy offload of heavy payloads to remote cloud GPUs when local capacity is constrained.
5. **Billing Supremacy Preemption:** Millisecond-level suspension of background tasks when POS checkout operations surge.
6. **Offline Data Persistence & Sync:** Resilient SQLite logging with automatic cloud PostgreSQL replication.

---

## 3. Specific Software Requirements

### 3.1 External Interface Requirements

#### 3.1.1 Software Interfaces
* **Host Operating System:** Windows 10/11 IoT Enterprise (Win32 APIs, DirectX 12) or Linux (POSIX, sysfs, DRM).
* **Machine Learning Backend:** ONNX Runtime v1.17+ with `DmlExecutionProvider` (Windows) and `VulkanExecutionProvider` (Linux).
* **KAN Engine:** `pykan` v0.0.5+ built on PyTorch 2.2+ (CPU inference mode).
* **Local Database:** SQLite 3.42+ with WAL support.
* **Remote Database:** PostgreSQL 15+ over TLS 1.3.

#### 3.1.2 Communication Interfaces
* **Task API:** HTTP/1.1 and HTTP/2 on port 8000 via FastAPI.
* **Cloud Fallback Stream:** gRPC / HTTP/2 over TLS 1.3 on port 443.
* **Telemetry Metric Scrape:** HTTP/1.1 on port 9090 (Prometheus text format).

---

### 3.2 Functional Requirements

#### Module 1: Hardware Telemetry Observer (`src.telemetry`)
* **SRS-TEL-001:** System shall sample available shared VRAM in megabytes every 250ms with $< 0.1\%$ CPU overhead.
* **SRS-TEL-002:** System shall intercept active POS checkout events and compute a rolling 5-second barcode scan rate ($S_{\text{rate}}$).
* **SRS-TEL-003:** System shall query APU die temperature via Windows DXGI/WMI or Linux `/sys/class/thermal`.
* **SRS-TEL-004:** Telemetry service shall expose a normalized state vector $\mathbf{x} \in [0.0, 1.0]^5$ via an in-memory thread-safe cache.

#### Module 2: KAN Gating Engine (`src.router`)
* **SRS-KAN-001:** System shall intercept all incoming tasks at `POST /api/v1/tasks/analyze`.
* **SRS-KAN-002:** KAN engine shall compute a continuous scalar execution score $S \in \mathbb{R}$ using learned cubic B-spline univariate functions across 5 input dimensions.
* **SRS-KAN-003:** KAN engine shall execute the forward pass in $\le 5.0\text{ ms}$ on a single CPU thread.
* **SRS-KAN-004:** System shall generate an exact algebraic symbolic formula string for every evaluation (e.g., `score(0.72) = 0.85*V - 1.24*Q ...`).
* **SRS-KAN-005:** If $S \ge 0.50$ and POS transaction count is 0, routing target shall be set to `LOCAL_IGPU`.
* **SRS-KAN-006:** If $S < 0.50$ or POS transaction count $> 0$, routing target shall be set to `CLOUD_GPU`.

#### Module 3: Local Inference Worker (`src.inference`)
* **SRS-INF-001:** System shall load INT8-quantized ONNX models targeting AMD Radeon iGPU via DirectML.
* **SRS-INF-002:** Inference worker shall restrict its execution thread pool to at most 2 threads.
* **SRS-INF-003:** Total resident memory (RSS) allocated to the inference session shall not exceed 512 MB.
* **SRS-INF-004:** If an emergency preemption interrupt signal is received from the Telemetry Observer, the inference worker shall abort the current frame execution within $5.0\text{ ms}$ and release the GPU context.

#### Module 4: Zero-Copy Cloud Fallback Buffer (`src.fallback`)
* **SRS-FAL-001:** In case of cloud routing, payloads exceeding 5 MB shall be read directly from shared memory (`/dev/shm` or Windows Named Section) without heap memory duplication.
* **SRS-FAL-002:** Fallback client shall stream payloads to cloud endpoints using gRPC with Snappy compression.
* **SRS-FAL-003:** Fallback client shall implement an exponential backoff circuit breaker with a 2000ms timeout.

#### Module 5: Resilient Local Store & Cloud Sync (`src.storage`)
* **SRS-STO-001:** System shall record all inference outputs, KAN scores, symbolic formulas, and financial attribution into a local SQLite database configured with `PRAGMA journal_mode=WAL`.
* **SRS-STO-002:** SQLite write operations shall be asynchronous and non-blocking relative to the API response.
* **SRS-STO-003:** A background sync daemon shall replicate unsynced SQLite records in batches of 100 to the central cloud PostgreSQL database every 60 seconds.
* **SRS-STO-004:** Local SQLite store shall retain records offline for a minimum of 7 days during WAN outages and resume synchronization upon reconnection without data loss.

---

### 3.3 Performance Requirements
* **NFR-PERF-01 (Zero Billing Degradation):** Under maximum concurrent analytics load, POS billing application latency shall not degrade by more than $0.00\text{ ms}$.
* **NFR-PERF-02 (Routing Overhead):** $P_{95}$ latency of the KAN routing decision shall be $\le 3.5\text{ ms}$; $P_{99} \le 5.0\text{ ms}$.
* **NFR-PERF-03 (Edge Inference Latency):** $P_{95}$ local execution of quantized YOLOv8-nano on $640\times640$ frames shall be $\le 120\text{ ms}$ on AMD Vega 8 iGPU.
* **NFR-PERF-04 (Memory Footprint):** Total steady-state memory consumption of the edge software stack shall not exceed 650 MB.

---

### 3.4 Software Safety & Security Attributes
* **NFR-SEC-01 (Zero Raw Video Egress):** Raw camera video frames shall be processed exclusively in volatile memory and purged immediately post-inference using `memset`.
* **NFR-SEC-02 (PCI-DSS Boundary):** The software shall run under an isolated user account (`analytics-worker`) without permissions to read USB HID card readers, magnetic stripe readers, or payment spool directories.
* **NFR-SEC-03 (mTLS Communications):** All cloud egress shall be authenticated using X.509 client certificates with TLS 1.3.

