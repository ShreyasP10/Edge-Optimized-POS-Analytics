# Edge & Cloud Deployment Guide
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Target Environments:** Windows 10/11 IoT Enterprise, Ubuntu 22.04 LTS POS, AWS / GCP Cloud Backend  

---

## 1. System Requirements & Prerequisites

### 1.1 Edge POS Hardware Requirements
* **Processor / APU:**
  * AMD Ryzen Embedded (V1605B, V2516, R1505G or later) or AMD Ryzen 3/5/7 PRO with Radeon Vega / RDNA integrated graphics.
  * *Alternative:* Intel Core i3/i5/i7 (11th Gen Tiger Lake or newer) with Intel Iris Xe Graphics.
* **Unified System Memory:** Minimum 8 GB DDR4/DDR5 (16 GB recommended).
  * UEFI/BIOS Setting: Allocate $\ge 2\text{GB}$ dedicated or dynamic shared aperture to the APU.
* **Storage:** 64 GB free disk space on SSD / NVMe.
* **Network:** Gigabit Ethernet or Enterprise 802.11ac Wi-Fi.

### 1.2 Driver & Software Prerequisites
* **Windows Host (Windows 10 / 11 IoT Enterprise 64-bit):**
  * AMD Software: Adrenalin Edition or AMD Enterprise Driver (v22.Q4 or newer).
  * DirectX 12 Feature Level 12_0 support (for DirectML).
  * Python 3.11+ x64.
  * Docker Desktop (Windows Containers or WSL2 backend) OR Native Windows Service via NSSM.
* **Linux Host (Ubuntu 22.04 LTS / SUSE Linux Point of Service):**
  * Linux Kernel $\ge 5.15$ with `amdgpu` driver module active.
  * Mesa Vulkan drivers: `mesa-vulkan-drivers` and `vulkan-tools`.
  * Verify GPU access: `vulkaninfo` and `clinfo`.
  * K3s (`v1.28+k3s1`).

---

## 2. Edge Node Installation & Setup

### 2.1 Linux POS (Native K3s Deployment)

#### Step 1: Install K3s with Resource Isolation Flags
Run the lightweight Kubernetes installer with system-reserved CPU/RAM flags to protect POS host processes:

```bash
curl -sfL https://get.k3s.io | sh -s - \
  --kubelet-arg="system-reserved=cpu=1500m,memory=2Gi" \
  --kubelet-arg="kube-reserved=cpu=500m,memory=1Gi" \
  --kubelet-arg="eviction-hard=memory.available<500Mi" \
  --write-kubeconfig-mode 644
```

#### Step 2: Configure cgroup v2 for the POS Billing Application
Ensure the billing process is placed inside the high-priority root slice:

```bash
# Verify cgroups v2
mount -t cgroup2

# Create protected slice for POS Billing
sudo systemctl set-property pos-billing.service \
  CPUWeight=1000 \
  IOWeight=1000 \
  OOMScoreAdjust=-1000
```

---

### 2.2 Windows POS Installation (Container or Native Service)

On Windows IoT terminals where Kubernetes cannot run natively, deploy using Docker Compose or as a managed Windows background service:

#### Option A: Docker Compose Deployment
```bash
# Clone the repository
git clone https://github.com/your-org/edge-pos-analytics.git
cd edge-pos-analytics

# Copy and configure environment variables
cp .env.example .env

# Build and start edge services
docker-compose up --build -d
```

#### Option B: Native Windows Service (DirectML Optimized)
```powershell
# Create Python virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install required dependencies
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install pykan onnxruntime-directml fastapi uvicorn[standard] prometheus-client httpx

# Verify DirectML recognizes the AMD Radeon iGPU
python -c "import onnxruntime as ort; print('Available Providers:', ort.get_available_providers())"
# Expected output contains: 'DmlExecutionProvider'
```

---

## 3. Kubernetes / K3s Production Manifests

### 3.1 PriorityClass Manifest (`priority-classes.yaml`)
Guarantees that analytics pods are evicted immediately under system stress:

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: low-priority-analytics
value: 1000
preemptionPolicy: Never
globalDefault: false
description: "Background edge analytics pods that yield immediately to POS operations."
```

### 3.2 Analytics Deployment Manifest (`edge-analytics-pod.yaml`)
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kan-edge-analytics
  namespace: edge-system
  labels:
    app: kan-edge-analytics
spec:
  replicas: 1
  selector:
    matchLabels:
      app: kan-edge-analytics
  template:
    metadata:
      labels:
        app: kan-edge-analytics
    spec:
      priorityClassName: low-priority-analytics
      containers:
      - name: router-and-inference
        image: edge-pos-analytics:v1.0.0
        imagePullPolicy: IfNotPresent
        resources:
          requests:
            cpu: "250m"
            memory: "512Mi"
          limits:
            cpu: "1500m"
            memory: "1536Mi"
        env:
        - name: STORE_ID
          value: "ST-0991"
        - name: TERMINAL_ID
          value: "POS-REG-01"
        - name: CLOUD_FALLBACK_URL
          value: "https://cloud-gpu.pos-analytics.internal/api/v1/infer"
        - name: KAN_MODEL_PATH
          value: "/app/models/kan_gate_weights.pt"
        - name: SQLITE_DB_PATH
          value: "/app/data/edge_analytics.db"
        ports:
        - containerPort: 8000
          name: api
        - containerPort: 9090
          name: metrics
        volumeMounts:
        - name: sqlite-storage
          mountPath: /app/data
        - name: dev-shm
          mountPath: /dev/shm
      volumes:
      - name: sqlite-storage
        hostPath:
          path: /var/lib/edge-analytics/data
          type: DirectoryOrCreate
      - name: dev-shm
        emptyDir:
          medium: Memory
          sizeLimit: 256Mi
```

---

## 4. Initializing the KAN Gating Model

Before live traffic is routed, train or calibrate the KAN router on the terminal's specific hardware characteristics:

```bash
# Execute KAN calibration script
python -m scripts.train_kan_gate \
  --vram-total-mb 4096 \
  --output-path models/kan_gate_weights.pt \
  --extract-symbolic True
```

This verifies:
1. B-spline grid calibration against memory allocator responsiveness.
2. DirectML device handle generation (`device_id=0`).
3. Symbolic formula extraction output to verify explainability.

---

## 5. Cloud Cluster Deployment (AWS / GCP)

### 5.1 Cloud Ingress & GPU Worker Pool
* **Orchestration:** Managed Kubernetes (EKS / GKE) with Karpenter or Cluster Autoscaler.
* **Worker Node Instance Types:**
  * AWS: `g4dn.xlarge` (NVIDIA T4 16GB) or `g5.xlarge` (NVIDIA A10G 24GB) spot instances.
  * GCP: `g2-standard-4` (NVIDIA L4 24GB).
* **Ingress:** Traefik or NGINX Ingress Controller enforcing mTLS with client certificates installed on each POS terminal.

### 5.2 Central PostgreSQL Database Setup
```sql
-- Cloud Database Initialization Script
CREATE TABLE IF NOT EXISTS store_terminals (
    terminal_id VARCHAR(64) PRIMARY KEY,
    store_id VARCHAR(32) NOT NULL,
    hardware_profile VARCHAR(128),
    installed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analytics_audit_ledger (
    audit_id UUID PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    store_id VARCHAR(32) NOT NULL,
    terminal_id VARCHAR(64) NOT NULL,
    task_type VARCHAR(64) NOT NULL,
    routing_decision VARCHAR(16) NOT NULL,
    kan_score DOUBLE PRECISION NOT NULL,
    kan_symbolic_formula TEXT NOT NULL,
    incurred_cost_usd NUMERIC(10, 6) DEFAULT 0.000000,
    features_payload JSONB NOT NULL
);

CREATE INDEX idx_ledger_store_time ON analytics_audit_ledger(store_id, timestamp);
CREATE INDEX idx_ledger_routing ON analytics_audit_ledger(routing_decision);
```

---

## 6. Observability & Monitoring Setup

### 6.1 Prometheus Scrape Configuration
Add the edge terminals to the store edge Prometheus instance (`prometheus.yml`):

```yaml
scrape_configs:
  - job_name: 'edge_pos_analytics'
    scrape_interval: 5s
    static_configs:
      - targets: ['localhost:9090']
        labels:
          store_id: 'ST-0991'
          tier: 'edge'
```

### 6.2 Key Grafana Alerting Rules
1. **Billing Supremacy Alert:**
   * Rule: `pos_checkout_scanner_rate_hz > 0 and rate(kan_routing_decision_total{decision="LOCAL_IGPU"}[1m]) > 0`
   * Severity: Critical. (Triggers if local GPU inference runs during active cashier scan burst).
2. **Cloud Spend Surge Alert:**
   * Rule: `sum(rate(kan_cloud_offload_cost_usd_total[1h])) > 10.0`
   * Severity: Warning. (Signals abnormal cloud offload volume; prompts KAN formula inspection).

---

## 7. Operations & Maintenance Runbook

### 7.1 Zero-Downtime Over-The-Air (OTA) Model Updates
To deploy an updated quantized ONNX model or KAN weights without restarting the service:
```bash
# Upload updated model to terminal
curl -X POST http://localhost:8000/api/v1/models/reload \
  -H "Authorization: Bearer <admin_token>" \
  -F "model_type=onnx_footfall" \
  -F "file=@models/footfall_v2_quant.onnx"
```
The FastAPI engine implements hot-swapping: new inference sessions are initialized in memory and atomic pointer swaps replace the active session with 0 dropped frames.

### 7.2 Troubleshooting Guide

| Symptom | Probable Cause | Action / Resolution |
| :--- | :--- | :--- |
| **All tasks route to CLOUD_GPU** | VRAM reading is 0 or DirectML device lost | Check driver with `dxdiag` or `vulkaninfo`. Restart service to reacquire GPU device context. |
| **Cashier reports scan delay** | Process priority or affinity misconfigured | Run `wmic process where name='pos_billing.exe' get priority` or `taskset -p <pid>`. Verify core pinning. |
| **SQLite database locked** | Non-WAL mode or high write concurrency | Run `sqlite3 edge_analytics.db "PRAGMA journal_mode;"`. If not WAL, execute `PRAGMA journal_mode=WAL;`. |
| **Cloud sync backlog growing** | Store WAN offline or invalid API key | Test egress connectivity: `curl -I https://cloud-gpu.pos-analytics.internal/health`. Local records remain safe in SQLite. |

