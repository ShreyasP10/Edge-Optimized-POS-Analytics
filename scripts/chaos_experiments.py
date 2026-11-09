import time
import sys
import os
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from src.main import app
from src.resilience.circuit_breaker import cloud_gpu_circuit_breaker, CircuitState
from src.resilience.kill_switches import kill_switch_manager
from src.telemetry.pos_monitor import pos_monitor

def run_chaos_experiments():
    print("=" * 80)
    print("      KAN-EDGE POS ANALYTICS: AUTOMATED CHAOS ENGINEERING EXPERIMENTS")
    print("=" * 80)

    client = TestClient(app)

    # ---------------------------------------------------------
    # Experiment 1: Dependency Failure & Circuit Breaker Trip
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("EXPERIMENT 1: CLOUD GPU DEPENDENCY FAILURE & CIRCUIT BREAKER TRIP")
    print("-" * 80)
    print("[*] Initial Circuit Breaker State:", cloud_gpu_circuit_breaker.state.value)

    # Force the circuit breaker to simulate consecutive upstream cloud outages
    for _ in range(cloud_gpu_circuit_breaker.failure_threshold):
        cloud_gpu_circuit_breaker._on_failure(TimeoutError("AWS Cloud GPU Connection Timeout (Simulated Chaos)"))

    print("[+] Circuit Breaker State after simulated outage:", cloud_gpu_circuit_breaker.state.value)
    assert cloud_gpu_circuit_breaker.state == CircuitState.OPEN, "Circuit breaker failed to trip to OPEN!"

    # Simulate checkout rush to force task to Cloud Fallback while circuit is OPEN
    pos_monitor.record_scan_event()
    pos_monitor.record_scan_event()

    task_req = {
        "task_type": "footfall_estimation",
        "payload_size_mb": 20.0,
        "latency_bound_ms": 500,
        "store_id": "ST-CHAOS-001"
    }
    resp = client.post("/api/v1/tasks/analyze", json=task_req)
    assert resp.status_code == 200
    data = resp.json()

    print("[+] Fast-Fail Graceful Degradation Response:")
    print(f"    - Routing:              {data['routing']}")
    print(f"    - Incurred Cloud Cost:  ${data['execution_metrics']['incurred_cost_usd']:.6f} (Protected!)")
    print(f"    - Cached Fallback Used: {data['result'].get('cached', False)}")
    print(f"    - Execution Time:       {data['execution_metrics']['total_time_ms']} ms")
    assert data["routing"] == "CLOUD_GPU_CACHED_FALLBACK", "Did not trigger cached fallback!"
    assert data["execution_metrics"]["incurred_cost_usd"] == 0.0, "Billed during outage!"

    # Reset circuit breaker
    cloud_gpu_circuit_breaker.force_state(CircuitState.CLOSED)
    print("[*] Circuit Breaker reset to:", cloud_gpu_circuit_breaker.state.value)

    # ---------------------------------------------------------
    # Experiment 2: Cashier Scan Hurricane ('Billing Always Wins')
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("EXPERIMENT 2: CASHIER SCAN HURRICANE (STORM PREEMPTION)")
    print("-" * 80)
    print("[*] Simulating extreme rush: 15 items scanned in 1 second...")
    for _ in range(15):
        pos_monitor.record_scan_event()

    print(f"[+] Scan rate recorded: {pos_monitor.get_scan_rate()} Hz")
    assert pos_monitor.is_preemption_active(), "Preemption circuit breaker failed to engage!"

    # Submit task during scan storm
    resp_rush = client.post("/api/v1/tasks/analyze", json={"task_type": "footfall_estimation", "payload_size_mb": 10.0, "latency_bound_ms": 500, "store_id": "ST-CHAOS-001"})
    assert resp_rush.status_code == 200
    rush_data = resp_rush.json()
    print(f"    - Routing Decision:     {rush_data['routing']}")
    print(f"    - Preemption Triggered: {rush_data['kan_evaluation']['preemption_triggered']}")
    print(f"    - Override Reason:      {rush_data['kan_evaluation']['override_reason']}")
    assert rush_data["kan_evaluation"]["preemption_triggered"] is True, "Preemption override failed!"

    # ---------------------------------------------------------
    # Experiment 3: Emergency Read-Only Mode (Disk Pressure / Full)
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("EXPERIMENT 3: DISK SATURATION EMERGENCY READ-ONLY DEGRADATION")
    print("-" * 80)
    kill_switch_manager.set_switch("READ_ONLY_MODE", True)
    print("[*] Kill Switch READ_ONLY_MODE engaged.")

    resp_ro = client.post("/api/v1/tasks/analyze", json={"task_type": "footfall_estimation", "payload_size_mb": 5.0, "latency_bound_ms": 500, "store_id": "ST-CHAOS-001"})
    assert resp_ro.status_code == 200
    print("[+] Task executed successfully without disk write lockup.")
    kill_switch_manager.set_switch("READ_ONLY_MODE", False)

    # ---------------------------------------------------------
    # Experiment 4: Idempotency Key Replay (Network Retry Dedup)
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("EXPERIMENT 4: IDEMPOTENCY KEY REPLAY PROTECTION")
    print("-" * 80)
    idemp_key = f"idem-chaos-test-{int(time.time())}"
    headers = {"Idempotency-Key": idemp_key}

    # First call: executes inference
    r1 = client.post("/api/v1/tasks/analyze", json={"task_type": "footfall_estimation", "payload_size_mb": 8.0, "latency_bound_ms": 500, "store_id": "ST-CHAOS-001"}, headers=headers)
    assert r1.status_code == 200
    task_id_1 = r1.json()["task_id"]
    lookup_1 = r1.headers.get("x-cache-lookup", "MISS")
    print(f"[+] Call 1: Generated Task ID {task_id_1} (Lookup: {lookup_1})")

    # Second call with identical key (simulating network drop retry)
    r2 = client.post("/api/v1/tasks/analyze", json={"task_type": "footfall_estimation", "payload_size_mb": 8.0, "latency_bound_ms": 500, "store_id": "ST-CHAOS-001"}, headers=headers)
    assert r2.status_code == 200
    task_id_2 = r2.json()["task_id"]
    lookup_2 = r2.headers.get("x-cache-lookup")
    replay_flag = r2.headers.get("x-idempotent-replay")
    print(f"[+] Call 2 (Duplicate): Returned Task ID {task_id_2} (Lookup: {lookup_2}, Replay: {replay_flag})")

    assert task_id_1 == task_id_2, "Idempotency replay returned different task ID!"
    assert lookup_2 == "HIT", "Did not hit idempotency cache!"

    print("\n" + "=" * 80)
    print("[PASSED] ALL CHAOS EXPERIMENTS COMPLETED WITH 100% RESILIENCE SUCCESS.")
    print("=" * 80)

if __name__ == "__main__":
    run_chaos_experiments()
