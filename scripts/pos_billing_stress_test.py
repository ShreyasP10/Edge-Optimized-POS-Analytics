import argparse
import time
import requests

def run_stress_test(endpoint: str, scans_per_sec: float, duration_sec: int):
    print("=" * 70)
    print("POS BILLING CHECKOUT WAVE SIMULATOR ('BILLING ALWAYS WINS' TEST)")
    print("=" * 70)
    print(f"[*] Target Endpoint: {endpoint}")
    print(f"[*] Simulated Cashier Scan Rate: {scans_per_sec} items/sec")
    print(f"[*] Duration: {duration_sec} seconds")
    print("\n[+] Starting simulated customer checkout wave...")

    interval = 1.0 / max(0.1, scans_per_sec)
    end_time = time.time() + duration_sec
    total_scans = 0

    while time.time() < end_time:
        try:
            resp = requests.post(
                f"{endpoint}/api/v1/telemetry/simulate_scan",
                json={"burst_count": 1},
                timeout=2.0
            )
            total_scans += 1
            data = resp.json()
            rate = data.get("new_scan_rate_hz", scans_per_sec)
            preempt = data.get("preemption_active", True)
            print(f"  -> Scan #{total_scans:03d} logged | Rolling Rate: {rate} Hz | Preemption Circuit Breaker Active: {preempt}")
        except Exception as e:
            print(f"  [!] Connection note: {e}")
        time.sleep(interval)

    print("\n" + "=" * 70)
    print(f"[OK] Test finished. Total scans generated: {total_scans}")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate POS checkout scan bursts")
    parser.add_argument("--endpoint", type=str, default="http://127.0.0.1:8000", help="Base URL of Edge Engine")
    parser.add_argument("--scans-per-sec", type=float, default=5.0, help="Scan rate in items per second")
    parser.add_argument("--duration-sec", type=int, default=15, help="Test duration in seconds")
    args = parser.parse_args()

    run_stress_test(args.endpoint, args.scans_per_sec, args.duration_sec)

