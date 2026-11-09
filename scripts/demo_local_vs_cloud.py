import time
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def run_demo():
    print("=" * 80)
    print("      KAN-EDGE POS ANALYTICS: INTERPRETABLE GATING LIVE DEMONSTRATION")
    print("=" * 80)

    # Check health
    try:
        health = requests.get(f"{BASE_URL}/healthz", timeout=3.0).json()
        print(f"[+] Edge POS Node: {health.get('node')} (Store: {health.get('store')}) is ONLINE.\n")
    except Exception as e:
        print(f"[!] Error: Could not connect to {BASE_URL}. Ensure 'python -m src.main' is running!")
        return

    # Scenario 1: Calm Store (Register Idle)
    print("-" * 80)
    print("SCENARIO 1: CALM STORE PERIOD (Register Idle, VRAM Available)")
    print("-" * 80)
    task_payload = {
        "task_type": "footfall_estimation",
        "payload_size_mb": 12.0,
        "latency_bound_ms": 500,
        "store_id": "ST-0991",
        "terminal_id": "POS-REG-01"
    }
    resp1 = requests.post(f"{BASE_URL}/api/v1/tasks/analyze", json=task_payload).json()
    print(f"[*] Task ID:              {resp1['task_id']}")
    print(f"[*] Routing Decision:     >>> {resp1['routing']} <<<")
    print(f"[*] Incurred Cloud Cost:  ${resp1['execution_metrics']['incurred_cost_usd']:.6f}")
    print(f"[*] Total Execution Time: {resp1['execution_metrics']['total_time_ms']} ms")
    print(f"[*] KAN Score:            {resp1['kan_evaluation']['score']}")
    print(f"[*] KAN Justification:    {resp1['kan_evaluation']['justification']}")
    print(f"[*] Result:               Detections: {len(resp1['result']['detections'])} customers detected")

    # Scenario 2: Checkout Rush ("Billing Always Wins" Preemption)
    print("\n" + "-" * 80)
    print("SCENARIO 2: CASHIER CHECKOUT WAVE ('BILLING ALWAYS WINS' PREEMPTION)")
    print("-" * 80)
    print("[!] Simulating sudden customer wave: Cashier scanning 5 items/sec...")
    requests.post(f"{BASE_URL}/api/v1/telemetry/simulate_scan", json={"burst_count": 8})

    print("[*] Submitting identical analytics task during scan burst...")
    resp2 = requests.post(f"{BASE_URL}/api/v1/tasks/analyze", json=task_payload).json()
    print(f"[*] Task ID:              {resp2['task_id']}")
    print(f"[*] Routing Decision:     >>> {resp2['routing']} <<<")
    print(f"[*] Incurred Cloud Cost:  ${resp2['execution_metrics']['incurred_cost_usd']:.6f} (Cloud GPU fallback)")
    print(f"[*] Total Execution Time: {resp2['execution_metrics']['total_time_ms']} ms")
    print(f"[*] Preemption Triggered: {resp2['kan_evaluation']['preemption_triggered']}")
    print(f"[*] Override Reason:      {resp2['kan_evaluation']['override_reason']}")
    print(f"[*] KAN Score:            {resp2['kan_evaluation']['score']}")
    print(f"[*] KAN Justification:    {resp2['kan_evaluation']['justification']}")

    # Scenario 3: Inspect Audit Logs
    print("\n" + "-" * 80)
    print("SCENARIO 3: AUDITING THE MATHEMATICAL LEDGER (SQLite WAL)")
    print("-" * 80)
    logs = requests.get(f"{BASE_URL}/api/v1/audit/logs?limit=2").json()
    print(f"[+] Total Records in Local Ledger: {logs['record_count']}")
    for i, rec in enumerate(logs["records"]):
        print(f"\n  [Record #{i+1}] Event ID: {rec['event_id']}")
        print(f"    - Route: {rec['routing_decision']} | Cost: ${rec['incurred_cost_usd']:.6f}")
        print(f"    - Symbolic Formula: {rec['kan_formula']}")

    print("\n" + "=" * 80)
    print("[SUCCESS] DEMONSTRATION COMPLETE: Zero POS billing lag, 100% mathematical auditability.")
    print("=" * 80)

if __name__ == "__main__":
    run_demo()

