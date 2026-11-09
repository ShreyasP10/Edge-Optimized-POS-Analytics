# API Reference & Integration Guide
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**API Version:** v1  
**Base URL (Localhost):** `http://127.0.0.1:8000/api/v1`  
**Base URL (Cloud Fallback):** `https://cloud-gpu.pos-analytics.internal/api/v1`  
**Authentication:** Header `X-Terminal-Token: <bearer_or_api_key>`  

---

## 1. Endpoints Overview

| Method | Endpoint | Description | Typical Latency |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/tasks/analyze` | Ingests analytics task, evaluates KAN gate, routes to local iGPU or cloud | 5ms routing + inference |
| `GET` | `/api/v1/telemetry/live` | Real-time node telemetry stream (SSE / WebSocket) | Real-time (1 Hz) |
| `GET` | `/api/v1/audit/logs` | Query local SQLite audit logs and KAN symbolic formulas | < 15ms |
| `POST` | `/api/v1/models/reload` | Hot-swap active ONNX or KAN model weights with zero downtime | < 200ms |
| `GET` | `/metrics` | Prometheus metrics scrape endpoint | < 5ms |
| `GET` | `/healthz` | Kubernetes liveness and readiness probe | < 2ms |

---

## 2. Detailed Endpoint Specifications

### 2.1 Submit Analytics Task (`POST /api/v1/tasks/analyze`)
Ingests a computer vision or predictive analytics task. The local KAN Gating Layer intercepts the request, evaluates live hardware and checkout queue conditions, and either executes on the local AMD/Intel iGPU via ONNX Runtime or relays the payload to the cloud GPU cluster.

#### Request Headers
* `Content-Type: application/json`
* `X-Terminal-Token: <token>` (Required)

#### Request Body
```json
{
  "task_type": "footfall_estimation",
  "payload_size_mb": 14.5,
  "latency_bound_ms": 500,
  "store_id": "ST-0991",
  "terminal_id": "POS-REG-03",
  "payload_ref": "shm://frame_buffer_88912",
  "camera_id": "CAM-ENTRANCE-01",
  "force_routing": null
}
```

#### Fields Description
* `task_type` *(string, required)*: Type of analytics. Allowed values: `footfall_estimation`, `dwell_time`, `heatmapping`, `re_identification`.
* `payload_size_mb` *(float, required)*: Approximate uncompressed tensor size in Megabytes.
* `latency_bound_ms` *(integer, required)*: Maximum acceptable execution SLA in milliseconds.
* `store_id` *(string, required)*: Store identifier.
* `terminal_id` *(string, optional)*: Unique POS terminal identifier.
* `payload_ref` *(string, optional)*: Pointer to shared memory ring buffer (`/dev/shm`) to avoid double serialization.
* `force_routing` *(string, optional)*: Testing override. Values: `LOCAL_IGPU`, `CLOUD_GPU`, or `null`.

#### Response (200 OK) - Local iGPU Execution
```json
{
  "task_id": "7f3b8c2a-9e12-4d56-b789-0123456789ab",
  "status": "COMPLETED",
  "routing": "LOCAL_IGPU",
  "kan_evaluation": {
    "score": 0.724,
    "decision_threshold": 0.500,
    "justification": "score(0.724) = 0.852*V(0.82) - 1.240*Q(0.00) - 0.412*S(0.29) + 0.285*L(0.50) + 0.190*T(0.75)",
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
    "current_occupancy": 18,
    "detections": [
      {
        "class": "person",
        "confidence": 0.94,
        "bbox": [120, 45, 260, 380]
      },
      {
        "class": "person",
        "confidence": 0.89,
        "bbox": [310, 80, 420, 395]
      }
    ]
  }
}
```

#### Response (200 OK) - Elastic Cloud Fallback
```json
{
  "task_id": "8a4c9d3e-0f23-5e67-c890-1234567890bc",
  "status": "COMPLETED",
  "routing": "CLOUD_GPU",
  "kan_evaluation": {
    "score": -0.612,
    "decision_threshold": 0.500,
    "justification": "score(-0.612) = 0.852*V(0.38) - 1.240*Q(0.85) - 0.412*S(0.40) + 0.285*L(0.60) + 0.190*T(0.45)",
    "preemption_triggered": true,
    "override_reason": "BILLING_SUPREMACY_ACTIVE_SCAN_BURST"
  },
  "execution_metrics": {
    "routing_time_ms": 1.9,
    "cloud_transfer_ms": 48.0,
    "inference_time_ms": 38.5,
    "total_time_ms": 88.4,
    "incurred_cost_usd": 0.000450
  },
  "result": {
    "footfall_delta": 4,
    "current_occupancy": 22
  }
}
```

---

### 2.2 Live Telemetry Stream (`GET /api/v1/telemetry/live`)
Provides a continuous Server-Sent Events (SSE) or WebSocket stream of live POS terminal metrics. Used by local store dashboards and diagnostics tools.

#### Response Headers
* `Content-Type: text/event-stream`
* `Cache-Control: no-cache`

#### Event Payload Example
```json
data: {
  "timestamp": "2026-11-09T14:32:00.100Z",
  "vram_total_mb": 4096,
  "vram_free_mb": 3140,
  "vram_utilization_pct": 23.3,
  "pos_billing": {
    "active_transactions": 0,
    "barcode_scans_rate_hz": 0.0,
    "payment_terminal_busy": false
  },
  "apu_temperature_celsius": 51.0,
  "last_kan_score": 0.742,
  "active_inference_provider": "DmlExecutionProvider"
}
```

---

### 2.3 Query Audit Logs (`GET /api/v1/audit/logs`)
Fetches historical routing decisions, KAN symbolic formulas, and financial attribution data from the local SQLite store.

#### Query Parameters
* `limit` *(integer, optional, default: 50)*: Number of logs to return.
* `offset` *(integer, optional, default: 0)*: Pagination offset.
* `routing` *(string, optional)*: Filter by `LOCAL_IGPU` or `CLOUD_GPU`.
* `start_timestamp` *(integer, optional)*: Epoch timestamp lower bound.

#### Response (200 OK)
```json
{
  "total_records": 1240,
  "records": [
    {
      "event_id": "aud-1029-4412",
      "timestamp": 1794234720,
      "task_type": "footfall_estimation",
      "routing_decision": "LOCAL_IGPU",
      "kan_score": 0.812,
      "kan_formula": "score(0.812) = 0.852*V(0.85) - 1.240*Q(0.00) ...",
      "incurred_cost_usd": 0.0000,
      "execution_time_ms": 114.2,
      "synced_to_cloud": 1
    }
  ]
}
```

---

### 2.4 Model Hot-Swap Endpoint (`POST /api/v1/models/reload`)
Enables zero-downtime updates of quantized ONNX models or KAN spline weights without interrupting the background service or POS software.

#### Request (Multipart Form Data)
* `model_type`: `kan_weights` or `onnx_runtime`
* `file`: Binary model payload (`.pt` or `.onnx`)

#### Response (200 OK)
```json
{
  "status": "SUCCESS",
  "message": "Model onnx_runtime reloaded successfully. DirectML session re-initialized.",
  "active_version": "v1.2.0-quant-int8",
  "reloaded_at_ms": 142.0
}
```

---

## 3. Code Examples

### 3.1 Python Integration Example
```python
import requests
import json

API_URL = "http://localhost:8000/api/v1/tasks/analyze"
HEADERS = {
    "Content-Type": "application/json",
    "X-Terminal-Token": "test-edge-token-0991"
}

payload = {
    "task_type": "footfall_estimation",
    "payload_size_mb": 12.0,
    "latency_bound_ms": 500,
    "store_id": "ST-0991",
    "terminal_id": "POS-REG-01"
}

response = requests.post(API_URL, headers=HEADERS, json=payload)
data = response.json()

print(f"Task ID: {data['task_id']}")
print(f"Routed To: {data['routing']}")
print(f"KAN Formula: {data['kan_evaluation']['justification']}")
print(f"Incurred Cost: ${data['execution_metrics']['incurred_cost_usd']}")
```

### 3.2 cURL CLI Example
```bash
curl -X POST http://localhost:8000/api/v1/tasks/analyze \
  -H "Content-Type: application/json" \
  -H "X-Terminal-Token: test-edge-token-0991" \
  -d '{
    "task_type": "footfall_estimation",
    "payload_size_mb": 15.0,
    "latency_bound_ms": 500,
    "store_id": "ST-0991"
  }'
```

