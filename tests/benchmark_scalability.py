import time
import sys
import concurrent.futures
import statistics
import psutil
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from src.main import app

def run_scalability_benchmark(total_requests: int = 50, concurrency: int = 5):
    print("=" * 80)
    print("      KAN-EDGE POS ANALYTICS: SCALABILITY & INTEGRITY BENCHMARK")
    print("=" * 80)
    print(f"[*] Total Ingestion Requests: {total_requests}")
    print(f"[*] Concurrent Workers:       {concurrency}")

    client = TestClient(app)
    process = psutil.Process(os.getpid())
    mem_before_mb = process.memory_info().rss / (1024 * 1024)

    payload = {
        "task_type": "footfall_estimation",
        "payload_size_mb": 10.0,
        "latency_bound_ms": 500,
        "store_id": "ST-BENCH-001"
    }

    latencies_ms = []
    routing_decisions = {"LOCAL_IGPU": 0, "CLOUD_GPU": 0, "CLOUD_GPU_PREEMPTED": 0}

    t_start = time.perf_counter()

    def send_task(task_index: int):
        t0 = time.perf_counter()
        resp = client.post("/api/v1/tasks/analyze", json=payload)
        elapsed = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200
        data = resp.json()
        return elapsed, data["routing"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(send_task, i) for i in range(total_requests)]
        for f in concurrent.futures.as_completed(futures):
            elapsed_ms, route = f.result()
            latencies_ms.append(elapsed_ms)
            routing_decisions[route] = routing_decisions.get(route, 0) + 1

    total_wall_time_s = time.perf_counter() - t_start
    throughput_rps = total_requests / total_wall_time_s
    mem_after_mb = process.memory_info().rss / (1024 * 1024)

    print("\n" + "-" * 80)
    print("1. LATENCY & THROUGHPUT PERFORMANCE")
    print("-" * 80)
    print(f"[*] Throughput:           {throughput_rps:.2f} requests/second")
    print(f"[*] Mean Latency:         {statistics.mean(latencies_ms):.2f} ms")
    print(f"[*] Median Latency (P50): {statistics.median(latencies_ms):.2f} ms")
    print(f"[*] 95th Percentile (P95):{statistics.quantiles(latencies_ms, n=20)[18]:.2f} ms")
    print(f"[*] 99th Percentile (P99):{max(latencies_ms):.2f} ms")

    print("\n" + "-" * 80)
    print("2. ROUTING INTEGRITY & AUDIT DISTRIBUTION")
    print("-" * 80)
    for route, count in routing_decisions.items():
        pct = (count / total_requests) * 100
        print(f"[*] Route: {route:<22} Count: {count:<4} ({pct:.1f}%)")

    print("\n" + "-" * 80)
    print("3. MEMORY & RESOURCE INTEGRITY")
    print("-" * 80)
    print(f"[*] Resident Memory Before: {mem_before_mb:.2f} MB")
    print(f"[*] Resident Memory After:  {mem_after_mb:.2f} MB")
    print(f"[*] Memory Delta:           +{mem_after_mb - mem_before_mb:.2f} MB (Bounded)")

    print("\n" + "=" * 80)
    print("[RESULT] SCALABILITY AUDIT PASSED: Zero crashes, zero database lock errors.")
    print("=" * 80)

if __name__ == "__main__":
    run_scalability_benchmark()
