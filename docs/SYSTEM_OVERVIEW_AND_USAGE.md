# System Overview & Step-by-Step Usage Guide
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Target Audience:** Store Operators, Retail DevOps, Software Engineers, and System Integrators  

---

## 1. What Is the Targeted System?

### 1.1 The Physical Target
The targeted system is a standard commercial **Point-of-Sale (POS) checkout terminal** or **Self-Checkout (SCO) kiosk** already deployed at checkout lanes in retail stores, supermarkets, and quick-service restaurants (QSR).

```
+----------------------------------------------------------------------------------------------------+
|                                    TARGET POS TERMINAL HARDWARE                                    |
|                                                                                                    |
|   [Cashier Touch Screen]         [Customer Facing Display]        [Barcode Scanner (USB HID)]      |
|             \                                |                               /                     |
|              v                               v                              v                      |
|       +-----------------------------------------------------------------------------+              |
|       |                     AMD RYZEN EMBEDDED / INTEL CORE APU                     |              |
|       |  - 4 Cores / 8 Threads (x86-64)                                             |              |
|       |  - Integrated GPU: AMD Radeon Vega (3-11 CUs) or Intel Iris Xe (48-96 EUs)  |              |
|       |  - Unified RAM: 8 GB or 16 GB Dual-Channel DDR4/DDR5                       |              |
|       |  - Storage: 128 GB+ NVMe / SATA SSD                                         |              |
|       |  - OS: Windows 10/11 IoT Enterprise (64-bit) or Ubuntu 22.04 LTS POS       |              |
|       +-----------------------------------------------------------------------------+              |
|              ^                                                               ^                     |
|              |                                                               |                     |
|     [Overhead Camera (PoE / USB)]                                  [Bank Card PIN Pad (EMV)]       |
+----------------------------------------------------------------------------------------------------+
```

### 1.2 Target Hardware Specifications
* **Processor / APU:**
  * AMD Ryzen Embedded (V1000/V2000, R1000 series) with Radeon Vega 3, 6, 8, or 11 graphics.
  * AMD Ryzen 3 / 5 / 7 PRO commercial desktop APUs (e.g., 4650G, 5650G).
  * Intel Core i3 / i5 / i7 (11th Gen Tiger Lake or newer) with Intel Iris Xe Graphics.
* **Unified Memory (RAM):** 8 GB to 16 GB DDR4/DDR5 (Dual-Channel required for GPU bandwidth).
* **Operating Systems:**
  * Windows 10 IoT Enterprise LTSC or Windows 11 IoT Enterprise (64-bit).
  * Ubuntu 22.04 LTS Point-of-Service / SUSE Linux Point of Service (SLEPOS 15).
* **Target Peripherals:** USB barcode scanners, receipt printers, touch display panels, and store overhead cameras (RTSP or USB UVC).

---

## 2. What Does It Do?

### 2.1 The Problem It Solves
1. **High Cloud Bills:** Continuous streaming of store security and analytics cameras to cloud GPUs (AWS/GCP) costs \$10,000–\$50,000/month per store chain.
2. **Latent Edge Power:** POS checkout machines sit in stores 24/7 with underutilized integrated GPUs (AMD Radeon Vega / Intel Iris Xe) doing almost nothing except rendering simple billing buttons.
3. **The Risk of Crashing Billing:** Traditional background AI programs are "scalar-blind." If a customer analytics task runs locally while a customer is paying, the billing screen lags or freezes, infuriating customers and cashiers.

### 2.2 The Solution
KAN-Edge turns the POS machine into an AI edge node while enforcing one sacred rule:
> **"Billing Always Wins."** Under zero circumstances may analytics slow down billing.

```
                          [Analytics Task: Footfall / Dwell-Time]
                                             |
                                             v
                             +-------------------------------+
                             |    KAN GATING LAYER (pykan)   |
                             | Checks:                       |
                             |  1. Free VRAM on APU          |
                             |  2. Active Barcode Scans      |
                             |  3. Payload Tensor Size       |
                             |  4. Latency SLA               |
                             +-------------------------------+
                                             |
                 +---------------------------+---------------------------+
                 | (If Register Idle & VRAM Free)                        | (If Cashier Scanning or High Load)
                 v                                                       v
   +---------------------------+                           +---------------------------+
   |   LOCAL iGPU INFERENCE    |                           |    ELASTIC CLOUD GPU      |
   | - ONNX Runtime (DirectML) |                           | - Zero-copy gRPC stream   |
   | - INT8 Quantized Model    |                           | - AWS / GCP GPU cluster   |
   | - Cost: $0.00             |                           | - Preserves 0ms POS lag   |
   +---------------------------+                           +---------------------------+
                 |                                                       |
                 +---------------------------+---------------------------+
                                             v
                             +-------------------------------+
                             |   MATHEMATICAL AUDIT LOG      |
                             | Outputs exact formula:        |
                             | score = 0.85*VRAM - 1.2*Queue |
                             +-------------------------------+
```

---

## 3. How It Works (Core Mechanisms)

1. **Hardware Telemetry Observer:** A micro-daemon continuously polls the APU's available shared VRAM and monitors cashier barcode scanner activity.
2. **Kolmogorov-Arnold Network (KAN) Gate:** A mathematical neural layer using B-splines. Unlike black-box neural networks, KAN evaluates live terminal capacity in $< 3.5\text{ms}$ and outputs an **exact algebraic formula** explaining its routing decision.
3. **Hardware-Accelerated Local Inference:** Executes quantized INT8 computer vision models (e.g., YOLOv8-nano for person detection) on the AMD Radeon iGPU via Microsoft DirectML (Windows) or Vulkan (Linux).
4. **Emergency 3.2ms Preemption:** If an item is scanned mid-inference, the KAN gate immediately yields the GPU context and transparently offloads tasks to the cloud.
5. **Offline-First Resilience:** Feature vectors are saved in a local SQLite database (WAL mode). If the store's internet goes down, analytics continue locally and sync to cloud PostgreSQL when the network returns.

---

## 4. Step-by-Step Process to Use

Here is the exact end-to-end process to set up, calibrate, and run KAN-Edge on hardware or a development machine.

### Step 1: Clone Repository & Install Dependencies
Ensure you have **Python 3.11+** installed:

```bash
# Clone the repository
git clone https://github.com/your-org/edge-pos-analytics.git
cd edge-pos-analytics

# Create and activate virtual environment
python -m venv venv

# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On Linux:
source venv/bin/activate

# Install required dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Copy the template configuration file:

```bash
# Copy sample configuration
cp .env.example .env
```
Key settings in `.env`:
* `STORE_ID`: Identifier for the store (e.g., `ST-0991`).
* `TERMINAL_ID`: Identifier for the POS lane (e.g., `POS-REG-01`).
* `VRAM_TOTAL_MB`: APU unified memory assigned to GPU (typically `2048` or `4096`).
* `KAN_DECISION_THRESHOLD`: Threshold for local vs. cloud routing (default `0.50`).

---

### Step 3: Train & Calibrate the KAN Gating Model
Before starting the service, train the KAN router on the terminal's hardware profile:

```bash
python -m scripts.train_kan_gate --vram-total-mb 4096 --extract-symbolic True
```
**What happens:**
* The B-spline grid ($G=5, k=3$) is trained on multi-variate load curves.
* It prunes non-essential pathways and outputs the symbolic formula.
* The calibrated weights are saved to `models/kan_gate_weights.pt`.

---

### Step 4: Start the Edge Analytics Engine
Launch the local FastAPI service:

```bash
python -m src.main
```
Or via Uvicorn:
```bash
uvicorn src.main:app --host 127.0.0.1 --port 8000 --workers 1
```
* The API will start on `http://127.0.0.1:8000`.
* The Prometheus metrics exporter will be live on `http://127.0.0.1:9090/metrics`.

---

### Step 5: Send Analytics Tasks (Usage Examples)

#### Example A: Normal Ingestion (Calm Register $\to$ Routed Locally)
Submit an analytics payload (e.g., footfall estimation batch from an overhead camera):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/analyze \
  -H "Content-Type: application/json" \
  -H "X-Terminal-Token: test-edge-token-0991" \
  -d '{
    "task_type": "footfall_estimation",
    "payload_size_mb": 12.0,
    "latency_bound_ms": 500,
    "store_id": "ST-0991",
    "terminal_id": "POS-REG-01"
  }'
```

**Expected JSON Response:**
```json
{
  "task_id": "7f3b8c2a-9e12-4d56-b789-0123456789ab",
  "status": "COMPLETED",
  "routing": "LOCAL_IGPU",
  "kan_evaluation": {
    "score": 0.742,
    "decision_threshold": 0.50,
    "justification": "score(0.742) = 0.852*V(0.82) - 1.240*Q(0.00) - 0.412*S(0.24) + 0.285*L(0.50) + 0.190*T(0.75)",
    "preemption_triggered": false
  },
  "execution_metrics": {
    "routing_time_ms": 2.8,
    "inference_time_ms": 112.4,
    "total_time_ms": 115.2,
    "incurred_cost_usd": 0.0000
  },
  "result": {
    "footfall_delta": 2,
    "current_occupancy": 18
  }
}
```
* **Notice:** `routing: "LOCAL_IGPU"` and `incurred_cost_usd: 0.0000`.

---

### Step 6: Test "Billing Always Wins" Preemption

To test how the system reacts during a cashier checkout rush:

In a separate terminal, run the simulated barcode scanner generator:
```bash
python -m scripts.pos_billing_stress_test --scans-per-sec 6
```

Now submit the exact same analytics task:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/analyze \
  -H "Content-Type: application/json" \
  -H "X-Terminal-Token: test-edge-token-0991" \
  -d '{
    "task_type": "footfall_estimation",
    "payload_size_mb": 12.0,
    "latency_bound_ms": 500,
    "store_id": "ST-0991",
    "terminal_id": "POS-REG-01"
  }'
```

**Expected JSON Response:**
```json
{
  "task_id": "9c1a2b3d-4e5f-6a7b-8c9d-0123456789cd",
  "status": "COMPLETED",
  "routing": "CLOUD_GPU",
  "kan_evaluation": {
    "score": -0.618,
    "decision_threshold": 0.50,
    "justification": "score(-0.618) = 0.852*V(0.40) - 1.240*Q(0.85) - 0.412*S(0.24) + 0.285*L(0.50) + 0.190*T(0.50)",
    "preemption_triggered": true,
    "override_reason": "BILLING_SUPREMACY_ACTIVE_SCAN_BURST"
  },
  "execution_metrics": {
    "routing_time_ms": 1.9,
    "total_time_ms": 85.1,
    "incurred_cost_usd": 0.000450
  }
}
```
* **Notice:** The task was instantly redirected to `CLOUD_GPU` because the scanner burst was active, preventing the POS billing screen from lagging even a millisecond!

---

### Step 7: View Live Telemetry & Audit Logs

* **Real-time Telemetry (Browser or cURL):**
  ```bash
  curl http://127.0.0.1:8000/api/v1/telemetry/live
  ```
* **Query Mathematical Audit Logs:**
  ```bash
  curl http://127.0.0.1:8000/api/v1/audit/logs?limit=5
  ```
* **Prometheus Metrics:**
  Open `http://127.0.0.1:9090/metrics` to see live gauges for `pos_checkout_active_transactions`, `pos_igpu_vram_free_bytes`, and `kan_cloud_offload_cost_usd_total`.

---

### Step 8: Production Deployment (Docker & K3s)

#### Via Docker Compose:
```bash
docker-compose up --build -d
```

#### Via K3s (Lightweight Kubernetes on Linux POS):
```bash
kubectl apply -f k8s/priority-classes.yaml
kubectl apply -f k8s/edge-analytics-deployment.yaml
```
The pod runs with `PriorityClass: low-priority-analytics`, ensuring that if system RAM ever approaches critical limits, the Linux kernel terminates the analytics container before touching the billing application.

