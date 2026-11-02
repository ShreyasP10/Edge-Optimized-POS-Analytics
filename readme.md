# KAN-Edge POS Analytics
A hybrid edge-cloud machine learning architecture for retail Point-of-Sale (POS) systems. This platform uses a Kolmogorov-Arnold Network (KAN) to dynamically route customer analytics tasks (foot-traffic, demand forecasting) between a checkout terminal's local integrated GPU (iGPU) and cloud servers, optimizing for zero-latency checkout and minimal cloud compute costs.

## 🎯 The Problem
Retail and food-service businesses face exorbitant cloud computing costs to run real-time AI for customer experience and inventory analytics. Standard POS hardware has latent compute power in integrated GPUs (like AMD Radeon), but traditional ML load balancers are scalar-blind. If a background AI task overwhelms the local terminal during a busy checkout wave, the billing software lags.

## 💡 The Solution: KAN-Gated Compute Routing
This architecture leverages the underutilized integrated GPUs already sitting inside standard checkout terminals.

Instead of a black-box scheduler, a Kolmogorov-Arnold Network (KAN) acts as a mathematically interpretable gating layer. When an analytics task is generated, the KAN profiles the task size against the live transaction load of the POS terminal. It generates a symbolic formula to determine whether the task can be processed locally via ONNX Runtime, or if it must be relayed to a cloud server to preserve terminal performance.

Core Rule: Billing always wins. Analytics pods are instantly throttled or offloaded to the cloud when POS checkout events spike.

## 🏗 System Architecture
The system operates on a localized edge mesh, capable of bursting to the cloud.

Edge Orchestration: K3s (Lightweight Kubernetes) runs as a background service on the POS hardware with strict resource limits.

The Decision Engine (KAN Gate): A localized Python API using pykan. It outputs human-readable algebraic formulas to justify why a specific task was processed locally or billed to the cloud.

Local Inference Engine: ONNX Runtime utilizes DirectML/Vulkan to run quantized ML models directly on the POS machine's AMD Radeon iGPU.

Cloud Fallback Pipeline: Zero-copy buffer relays heavy tasks (e.g., multi-camera Re-ID) to AWS/GCP cloud GPUs.

Distributed Data: SQLite manages local edge features to ensure operations survive network drops, while heavy analytics sync asynchronously to a Cloud Object Store.

## 🛠 Tech Stack
Orchestration: K3s

Routing / ML: PyTorch, pykan

Inference: ONNX Runtime (DirectML / Vulkan support)

Backend: Python 3.11, FastAPI

Database: SQLite (Edge), PostgreSQL (Cloud Sync)

Observability: Prometheus (tracking live iGPU load & VRAM overhead)

## 🚀 Getting Started
Prerequisites
Windows/Linux POS terminal with an AMD Ryzen/Radeon APU (or equivalent Intel iGPU).

Python 3.11+

K3s (or Minikube for local development)

Docker & Docker Compose

Local Development Setup
Clone the repository:

```
git clone https://github.com/your-org/edge-pos-analytics.git
cd edge-pos-analytics
```
Configure Environment:
Copy the example environment variables and add your cloud fallback credentials.

Bash
cp .env.example .env
Deploy the Edge Services:
Spin up the local KAN gate, SQLite store, and FastAPI task queue.
```
docker-compose up --build -d
```
Initialize the KAN Router:
Train the baseline KAN model on sample POS load data.
```
python -m scripts.train_kan_gate
```
🔌 API Usage
Submit an analytics task to the local POS terminal. The KAN gate will automatically intercept the payload, evaluate current VRAM and checkout queue length, and route it to either the local ONNX runtime or the cloud.

```
curl -X POST http://localhost:8000/api/v1/tasks/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "footfall_estimation",
    "payload_size_mb": 15,
    "latency_bound_ms": 500,
    "store_id": "ST-0991"
  }'
Example Response (Routed Locally):
```
JSON
```
{
  "status": "processing",
  "routing": "LOCAL_IGPU",
  "kan_justification": "score(0.2) = 0.85 * available_vram - 1.2 * live_checkout_events",
  "estimated_completion_ms": 120
}
```
# 🔒 Security & Compliance
Data Minimization: Raw video streams and PII never leave the local POS terminal unless explicitly required for a heavy cloud task. Feature extraction happens on the edge.

Auditability: The KAN gate's symbolic output ensures that business managers have a mathematical audit trail explaining exactly why cloud computing costs were incurred at any given time.
Data Minimization: Raw video streams and PII never leave the local POS terminal unless explicitly required for a heavy cloud task. Feature extraction happens on the edge.

Auditability: The KAN gate's symbolic output ensures that business managers have a mathematical audit trail explaining exactly why cloud computing costs were incurred at any given time.


## 👨‍💻 Developer

| **Name** | **Role** | **Link** |
|---|---|---|
| **Atharva Mahajan** | *Lead Developer* | [GitHub](https://github.com/mahajanatharva1042) |
| **Shreyas Dinesh Pawar** | *Collaborator* | [GitHub](https://github.com/ShreyasP10) |
