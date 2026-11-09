# Product Requirements Document (PRD)
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Status:** Approved / Architecture-Ready  
**Target Release:** v1.0-GA  

---

## 1. Executive Summary

### 1.1 Overview
Modern retail stores, supermarkets, quick-service restaurants (QSR), and food-service chains seek real-time computer vision and machine learning analytics—such as customer footfall, queue dwell-time, heatmaps, loss prevention, and dynamic demand forecasting. Historically, deploying such AI solutions has forced businesses into an agonizing trade-off: either pay prohibitive cloud compute and egress bills (streaming high-resolution video streams to centralized AWS/GCP cloud GPUs) or deploy expensive, dedicated on-premise edge servers in cramped store back-offices.

**KAN-Edge POS Analytics** breaks this paradigm by repurposing existing, deployed Point-of-Sale (POS) checkout terminals into localized edge compute nodes. By tapping into the latent, underutilized integrated GPUs (iGPUs)—such as AMD Ryzen APUs (Radeon Graphics) and Intel Iris Xe processors—already powering standard cash registers, retailers run computer vision and predictive models on-premise at essentially zero incremental hardware cost.

### 1.2 The Innovation: The KAN Gating Layer
Traditional machine learning load balancers and container schedulers are **scalar-blind**: they treat nodes as homogeneous compute pools and cannot dynamically anticipate the sudden spike of customer checkout transactions. Running unconstrained background AI tasks on a checkout terminal risks monopolizing memory bandwidth, GPU cores, and CPU cycles, causing the mission-critical POS billing application to freeze or lag during peak shopping waves.

KAN-Edge solves this by introducing an intelligent, mathematically interpretable gating layer based on **Kolmogorov-Arnold Networks (KAN)**. When an analytics workload (e.g., video frame batch, customer re-identification, or inventory inference) is received, the KAN Gate dynamically computes terminal telemetry (available VRAM, CPU temperature, transaction event frequency, checkout queue size) against task requirements (payload size, latency SLA). 

Rather than relying on an opaque deep-learning black-box, the KAN engine produces a **symbolic, human-readable algebraic formula** justifying every routing decision:
$$\text{Score} = f(V_{\text{avail}}, Q_{\text{len}}, S_{\text{payload}}, L_{\text{bound}})$$

### 1.3 Core Axiom: Billing Always Wins
The foundational operational policy of the system is:
> **Billing Always Wins.** Under zero circumstances may an analytics task cause a perceptible frame drop, transaction lag, or UI latency penalty on the POS billing software. If checkout events spike or memory thresholds are pressured, background analytics pods are instantly throttled, paused, or transparently offloaded to the cloud.

---

## 2. Target Users & Stakeholders

| Persona | Role & Organization | Primary Pain Points | Goals & Value Derived |
| :--- | :--- | :--- | :--- |
| **Retail & Food-Service Business Owner / VP of Ops** | Primary Executive Sponsor (Retail chains, franchises, supermarkets, QSR) | • Prohibitive cloud GPU bills (\$10k-\$50k/month for continuous camera streaming).<br>• Cannot justify buying dedicated AI server racks for 500+ store branches.<br>• Lack of visibility into why cloud bills surge. | • Eliminate raw video cloud egress costs.<br>• Repurpose existing checkout registers with \$0 new hardware spend.<br>• Transparent mathematical audit trail justifying any cloud fallback costs. |
| **Store Operations Manager** | On-the-ground store manager / shift supervisor | • Customer lines piling up if POS software lags or crashes.<br>• Lack of real-time store footfall and aisle conversion insights.<br>• Internet outages break cloud-dependent tools. | • Zero impact on checkout speed or cashier workflow.<br>• Real-time local insights (queue alerts, foot traffic).<br>• System keeps functioning offline during ISP disruptions. |
| **Retail IT Administrator & DevOps Engineer** | Secondary Technical User (IT infrastructure, POS fleet management) | • High maintenance overhead for disparate store hardware.<br>• Fear of untested AI workloads crashing mission-critical POS terminals.<br>• PCI-DSS compliance audits and security boundaries. | • Lightweight orchestration via K3s with strict cgroup isolation.<br>• One-click deployment and automated rollbacks.<br>• Complete audit logging and Prometheus monitoring. |
| **Chief Information Security Officer (CISO) & Legal** | Governance, Security, and Compliance Officer | • GDPR, CCPA, and Biometric privacy violations if customer video streams leave store premises.<br>• PCI-DSS audit failure if analytics code touches cardholder data environments (CDE). | • Guaranteed edge-first data minimization: raw video never leaves the terminal.<br>• Only anonymized vector embeddings and aggregated metrics sync to cloud.<br>• Strict process and network isolation between POS billing and analytics pods. |

---

## 3. Product Vision & Value Propositions

```
+-----------------------------------------------------------------------------------+
|                            KAN-EDGE VALUE PROPOSITIONS                            |
+-----------------------------------------------------------------------------------+
|  1. ZERO INCREMENTAL HARDWARE   | Uses existing AMD Radeon / Intel iGPUs in POS   |
|  2. BILLING SUPREMACY           | POS checkout guaranteed 0ms added latency       |
|  3. MATHEMATICAL AUDITABILITY   | KAN outputs symbolic formula for every routing  |
|  4. DATA MINIMIZATION & PRIVACY | Raw video & PII stay on-device; zero raw egress |
|  5. OFFLINE RESILIENCE          | SQLite edge-first store survives network drops  |
|  6. ELASTIC CLOUD BURSTING      | Zero-copy offloading to cloud GPU when needed   |
+-----------------------------------------------------------------------------------+
```

### 3.1 Key Differentiators
1. **Interpretable Decision Routing (KAN vs. Black-Box MLP):** Unlike standard neural load-balancers that emit unexplainable logits, KAN outputs symbolic mathematical equations that retail CFOs and IT directors can audit to understand why every single cloud task was offloaded.
2. **Deterministic Preemption:** Dedicated hardware telemetry sensors monitor POS input events (barcode scans, payment terminal interactions) and throttle local inference pods in less than 5 milliseconds.
3. **Bandwidth Optimization:** Traditional setups stream 1080p/4K RTSP streams (3–8 Mbps per camera) over commercial broadband. KAN-Edge extracts features locally and transmits only aggregated JSON payloads (< 2 KB/min), reducing network bandwidth consumption by over 99%.

---

## 4. User Journeys & Scenarios

### 4.1 Scenario A: Calm Afternoon (Local iGPU Processing)
* **Context:** A grocery checkout terminal is running during an off-peak period (Tuesday 2:30 PM). 
* **Event:** An overhead security camera feeds a batch of frames to the local K3s analytics pod to estimate customer footfall and cart size.
* **Telemetry:** 
  * Checkout Queue: 0 active transactions.
  * Available APU Shared VRAM: 3.8 GB free.
  * CPU Usage: 12%.
* **KAN Gate Action:** The KAN Gate evaluates inputs and yields a high local execution score:
  $$\text{Score} = 0.85 \times 3.8 - 1.2 \times 0 - 0.04 \times 15 = 2.63 \quad (\ge 0.5 \implies \text{LOCAL})$$
* **Result:** Frame batch is processed in 95ms via ONNX Runtime accelerated by DirectML/Vulkan on the AMD Radeon iGPU. Extracted footfall count (+1) is recorded in local SQLite. Cloud cost = \$0.00.

### 4.2 Scenario B: Peak Rush Hour ("Billing Always Wins" Preemption)
* **Context:** Friday 6:15 PM rush. The cashier is actively scanning items and processing card payments.
* **Event:** Store vision pipeline dispatches a multi-camera customer Re-Identification (Re-ID) batch (payload: 45 MB).
* **Telemetry:** 
  * Checkout Queue: 4 pending transactions; active barcode scanner polling rate high.
  * Available APU Shared VRAM: 1.1 GB.
  * CPU Usage: 68%.
* **KAN Gate Action:** The KAN Gate evaluates inputs:
  $$\text{Score} = 0.85 \times 1.1 - 1.2 \times 4 - 0.04 \times 45 = -5.66 \quad (< 0.5 \implies \text{CLOUD})$$
* **Result:** Task is instantaneously routed via zero-copy buffer to the AWS/GCP cloud GPU cluster. POS billing UI remains completely smooth with zero frame stutter or scan latency. Audit log records the mathematical justification for the cloud egress.

### 4.3 Scenario C: Cloud Outage / Network Disconnection
* **Context:** Fiber optic cut outside store causes an ISP drop.
* **Event:** Periodic analytics tasks continue to arrive.
* **Resilience Mechanism:** KAN Gate detects network egress unavailability. It drops low-priority tasks (e.g., long-term heatmapping) and queues critical analytics (store footfall) for opportunistic local iGPU execution strictly between checkout scans. All results are written locally to SQLite in Write-Ahead Logging (WAL) mode. Once internet connectivity is restored, the local sync worker resumes batched transmission to central PostgreSQL.

---

## 5. Functional Requirements

### 5.1 Edge Orchestration & Workload Isolation (REQ-ORCH)
* **REQ-ORCH-01:** System must deploy via K3s (lightweight Kubernetes) or standalone containerized agent running as a low-priority background OS daemon on Windows POS (via WSL2/Native Windows Containers) and Linux POS.
* **REQ-ORCH-02:** Strict OS-level cgroup v2 limits must be enforced:
  * POS Billing Software: Assigned to dedicated CPU cores with real-time process priority (`nice -20` or Windows `HIGH_PRIORITY_CLASS`).
  * Analytics Pod: Hard ceiling of $\le 50\%$ CPU usage and $\le 60\%$ shared GPU VRAM.
* **REQ-ORCH-03:** Analytics container must run under low I/O priority (`ionice -c 3` / idle).
* **REQ-ORCH-04:** K3s pod eviction policies must prioritize analytics termination before any retail system component faces memory pressure.

### 5.2 KAN Dynamic Routing Layer (REQ-KAN)
* **REQ-KAN-01:** Local Python API (FastAPI) must intercept every incoming analytics payload.
* **REQ-KAN-02:** Feature extraction module must sample node state in $< 2\text{ms}$:
  1. $V_{\text{avail}}$: Available Shared Video Memory / RAM (GB).
  2. $Q_{\text{len}}$: Live checkout transactions / cashier keystroke activity index.
  3. $S_{\text{payload}}$: Analytics payload tensor size (MB).
  4. $L_{\text{bound}}$: Maximum tolerable latency SLA (ms).
  5. $T_{\text{cpu}}$: Node CPU temperature and thermal throttling indicator.
* **REQ-KAN-03:** The KAN model (implemented via `pykan` / PyTorch) must compute a scalar execution score and produce an extracted symbolic algebraic formula.
* **REQ-KAN-04:** Thresholding logic:
  * Score $\ge \tau$ (Default: 0.50): Dispatch to Local ONNX Runtime.
  * Score $< \tau$: Dispatch to Elastic Cloud Fallback.
* **REQ-KAN-05:** Decision latency for the KAN Gate must not exceed $5\text{ms}$.

### 5.3 Local Inference Engine (REQ-INF)
* **REQ-INF-01:** Inference runtime must utilize ONNX Runtime with hardware acceleration providers:
  * `DmlExecutionProvider` (DirectML) for Windows AMD/Intel iGPUs.
  * `VulkanExecutionProvider` / `OpenVINOExecutionProvider` for Linux POS distributions.
* **REQ-INF-02:** All deployed edge models must be quantized to INT8 or FP16 to minimize memory footprint and execution latency.
* **REQ-INF-03:** The inference worker must support instant interruption/cancellation if a POS billing spike occurs mid-inference.

### 5.4 Elastic Cloud Fallback (REQ-CLD)
* **REQ-CLD-01:** When cloud offload is selected, task payload must be passed through a zero-copy buffer to minimize memory allocations on the POS terminal.
* **REQ-CLD-02:** Upstream transmission must use authenticated gRPC / HTTP/2 with TLS 1.3 to AWS/GCP cloud endpoints.
* **REQ-CLD-03:** If cloud endpoint is unreachable (network timeout $> 2000\text{ms}$), task must gracefully degrade (downsample frame, queue, or discard non-essential frames) without blocking the POS.

### 5.5 Distributed Storage & Offline Resilience (REQ-DAT)
* **REQ-DAT-01:** Edge terminal must maintain a local SQLite database configured with WAL mode (`journal_mode=WAL`) and `synchronous=NORMAL` for high-throughput, crash-safe local logging.
* **REQ-DAT-02:** Local store must buffer at least 7 days of aggregated analytics features offline.
* **REQ-DAT-03:** Sync worker must asynchronously replicate batched feature records to central PostgreSQL in the cloud upon network availability.
* **REQ-DAT-04:** Raw video frames must be purged immediately from RAM/disk post-inference.

### 5.6 Mathematical Auditability & Cost Governance (REQ-AUD)
* **REQ-AUD-01:** Every task execution log must store:
  * Unique Task UUID and Timestamp.
  * Routing Decision (`LOCAL_IGPU` vs `CLOUD_GPU`).
  * Telemetry snapshot vector.
  * Human-readable KAN formula and computed score.
  * Estimated cloud cost incurred (\$0.00 for local, \$0.00045/infer for cloud).
* **REQ-AUD-02:** Provide an exportable audit report for finance/DevOps to reconcile AWS/GCP cloud bills against POS peak sales hours.

---

## 6. Non-Functional Requirements (NFR)

### 6.1 Performance & Latency
* **POS Checkout Impact:** $0.00\text{ms}$ added latency on barcode scan, receipt printing, or credit card PIN pad processing.
* **Routing Decision Latency:** $P_{95} \le 5\text{ms}$; $P_{99} \le 10\text{ms}$.
* **Local iGPU Inference Latency:** $P_{95} \le 180\text{ms}$ for footfall/object detection on $640\times640$ frames.
* **Memory Footprint:** Edge analytics runtime (FastAPI + KAN Gate + ONNX Runtime) must consume $< 750\text{MB}$ total resident memory (RSS).

### 6.2 Reliability & Availability
* **POS System Uptime:** 99.999% availability for core billing application.
* **Edge Agent Self-Healing:** Kubernetes/systemd watchdog must restart unresponsive analytics pods within 3 seconds.
* **Crash Isolation:** An uncaught exception, segmentation fault, or out-of-memory event in the analytics container must NEVER crash the host OS or POS application.

### 6.3 Security, Privacy & Compliance
* **PCI-DSS Compliance:** The analytics pod must have no access to the Payment Application Data Environment (CDE). No access to card reader peripherals, magnetic stripes, EMV chip data, or POS receipt spoolers.
* **Data Minimization:** No raw camera feeds, customer faces, or PII stored on disk or transmitted across public networks.
* **Network Isolation:** Edge analytics communicates exclusively over an encrypted loopback socket or isolated container network bridge.

---

## 7. Success Metrics & Key Performance Indicators (KPIs)

```
+-----------------------------------+-----------------------------------+
| METRIC                            | TARGET KPI                        |
+-----------------------------------+-----------------------------------+
| Cloud Compute Cost Reduction      | >= 70% reduction vs full cloud    |
| POS Billing Latency Degradation   | Exactly 0.0% (Zero measurable lag)|
| Local Edge Execution Ratio        | >= 65% of all daily analytics     |
| KAN Routing Decision Overhead     | < 5 milliseconds                  |
| Mathematical Audit Coverage       | 100% of routing events explained  |
| Offline Functionality Retention   | 100% local analytics buffered     |
| Network Bandwidth Savings         | >= 95% reduction vs raw RTSP      |
+-----------------------------------+-----------------------------------+
```

---

## 8. Release Roadmap

### Phase 1: MVP / Core Engine (Month 1–2)
* Local FastAPI routing service integrated with trained `pykan` model.
* ONNX Runtime with DirectML execution provider on AMD Radeon/Intel APU.
* Basic synthetic telemetry simulator (mocking checkout queue & VRAM).
* Local SQLite logging with symbolic KAN formula string output.

### Phase 2: Edge Hardening & Preemption (Month 3–4)
* Native telemetry integration: Windows ETW / Linux `procfs` to intercept real POS scan events.
* K3s deployment manifest with hard cgroups v2 limits and priority classes.
* DirectML/Vulkan zero-copy memory buffer.
* Elastic fallback client streaming to AWS/GCP GPU endpoint via gRPC.

### Phase 3: Cloud Sync & Cost Auditability Dashboard (Month 5–6)
* Asynchronous SQLite $\to$ PostgreSQL background sync worker.
* Prometheus metrics exporter + Grafana dashboard displaying live POS load vs. cloud spend.
* Enterprise audit log export tool for CFO/DevOps reconciliation.
* Multi-store pilot rollout across 50 retail checkout terminals.

