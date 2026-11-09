import unittest
import time
import threading
import json
import os
import tempfile
from pathlib import Path

# Set test environment
os.environ["STORE_ID"] = "ST-TEST-001"
os.environ["TERMINAL_ID"] = "POS-TEST-REG"

from src.config import settings
from src.telemetry.hardware_observer import HardwareObserver
from src.telemetry.pos_monitor import POSMonitor
from src.router.kan_gate import KANGate
from src.router.preemption import PreemptionManager
from src.inference.onnx_engine import ONNXInferenceEngine
from src.inference.preprocessor import IngestionPreprocessor
from src.fallback.cloud_client import CloudFallbackClient
from src.storage.sqlite_store import SQLiteStore
from fastapi.testclient import TestClient
from src.main import app

class TestSystemIntegrityAndScalability(unittest.TestCase):
    """
    Comprehensive verification suite testing:
    1. System & Code Integrity
    2. Scalability & Concurrency
    3. 'Billing Always Wins' Preemption
    4. Data Minimization & Privacy
    5. API Endpoints & Observability
    """

    def setUp(self):
        # Create an isolated temporary SQLite database for test isolation
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.store = SQLiteStore(db_path=self.temp_db.name)
        self.client = TestClient(app)

    def tearDown(self):
        try:
            os.remove(self.temp_db.name)
            # Remove WAL / SHM files if created
            for ext in ["-wal", "-shm"]:
                wal_file = self.temp_db.name + ext
                if os.path.exists(wal_file):
                    os.remove(wal_file)
        except Exception:
            pass

    # --- 1. HARDWARE TELEMETRY & OBSERVABILITY INTEGRITY ---
    def test_01_hardware_telemetry_integrity(self):
        observer = HardwareObserver(vram_total_mb=4096.0)
        state = observer.sample_state()

        self.assertIn("vram_free_ratio", state)
        self.assertIn("thermal_headroom_ratio", state)
        self.assertIn("cpu_utilization_pct", state)
        self.assertIn("die_temp_celsius", state)

        # Mathematical Bounds Verification: Ratios must strictly be in [0.0, 1.0]
        self.assertGreaterEqual(state["vram_free_ratio"], 0.0)
        self.assertLessEqual(state["vram_free_ratio"], 1.0)
        self.assertGreaterEqual(state["thermal_headroom_ratio"], 0.0)
        self.assertLessEqual(state["thermal_headroom_ratio"], 1.0)

    # --- 2. POS BILLING & PREEMPTION INTEGRITY ---
    def test_02_pos_checkout_monitor_and_preemption(self):
        monitor = POSMonitor(rolling_window_sec=2.0)

        # Baseline: Idle register
        self.assertFalse(monitor.is_preemption_active())
        self.assertEqual(monitor.get_scan_rate(), 0.0)

        # Simulate cashier scanning items
        for _ in range(5):
            monitor.record_scan_event()

        self.assertGreaterEqual(monitor.get_scan_rate(), 2.0)
        # Preemption MUST trigger when cashier scan burst occurs
        self.assertTrue(monitor.is_preemption_active())

        # Test EMV payment terminal busy penalty
        monitor.set_payment_state(True)
        self.assertTrue(monitor.is_preemption_active())
        self.assertGreaterEqual(monitor.get_checkout_pressure_index(), 0.2)

    # --- 3. KAN GATING MATHEMATICAL ACCURACY ---
    def test_03_kan_gating_logic_and_formula_extraction(self):
        gate = KANGate(threshold=0.50)

        # Case A: Calm register, light payload (10 MB, 500ms SLA)
        res_calm = gate.evaluate(payload_size_mb=10.0, latency_bound_ms=500)
        self.assertIn("routing", res_calm)
        self.assertIn("kan_score", res_calm)
        self.assertIn("justification", res_calm)

        # Justification must be an interpretable formula string
        self.assertTrue(res_calm["justification"].startswith("score("))
        self.assertIn("0.852*V", res_calm["justification"])
        self.assertIn("1.240*Q", res_calm["justification"])

        # Case B: Massive payload (90 MB) exceeding edge safe budget
        res_heavy = gate.evaluate(payload_size_mb=90.0, latency_bound_ms=100)
        # Higher payload penalizes score
        self.assertLess(res_heavy["kan_score"], res_calm["kan_score"])

    # --- 4. DATA MINIMIZATION & PCI-DSS HYGIENE ---
    def test_04_data_minimization_and_privacy(self):
        pre = IngestionPreprocessor()
        meta = pre.sanitize_and_format("shm://frame_tensor_441")
        self.assertTrue(meta["sanitized_pii"])
        self.assertFalse(meta["raw_video_retained"])

    # --- 5. SQLITE WAL STORAGE & CONCURRENCY SCALABILITY ---
    def test_05_sqlite_wal_concurrent_scalability(self):
        num_threads = 10
        records_per_thread = 20

        def worker(thread_id: int):
            for i in range(records_per_thread):
                event_id = f"evt-thread-{thread_id}-{i}"
                self.store.record_event(
                    event_id=event_id,
                    task_type="footfall_estimation",
                    routing_decision="LOCAL_IGPU",
                    kan_score=0.75,
                    kan_formula="score(0.75) = 0.85*V - 1.2*Q",
                    payload_size_mb=12.0,
                    execution_time_ms=110.5,
                    incurred_cost_usd=0.0000,
                    telemetry_snapshot={"thread": thread_id, "vram": 3200}
                )

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all 200 records persisted without lock failure
        logs = self.store.query_audit_logs(limit=300)
        self.assertEqual(len(logs), num_threads * records_per_thread)

    # --- 6. FASTAPI ENDPOINT FUNCTIONALITY & RESILIENCE ---
    def test_06_fastapi_analyze_and_audit_endpoints(self):
        # 1. Test Healthz
        r_health = self.client.get("/healthz")
        self.assertEqual(r_health.status_code, 200)
        self.assertEqual(r_health.json()["status"], "HEALTHY")

        # 2. Test Ingestion API
        task_data = {
            "task_type": "footfall_estimation",
            "payload_size_mb": 14.0,
            "latency_bound_ms": 500,
            "store_id": "ST-TEST-001"
        }
        r_analyze = self.client.post("/api/v1/tasks/analyze", json=task_data)
        self.assertEqual(r_analyze.status_code, 200)
        data = r_analyze.json()

        self.assertIn("task_id", data)
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn(data["routing"], ["LOCAL_IGPU", "CLOUD_GPU"])
        self.assertIn("score", data["kan_evaluation"])
        self.assertIn("justification", data["kan_evaluation"])

        # 3. Test Audit Logs API
        r_audit = self.client.get("/api/v1/audit/logs?limit=5")
        self.assertEqual(r_audit.status_code, 200)
        self.assertGreaterEqual(r_audit.json()["record_count"], 1)

    # --- 7. PROMETHEUS SCRAPE INTEGRITY ---
    def test_07_prometheus_metrics_integrity(self):
        r_metrics = self.client.get("/metrics")
        self.assertEqual(r_metrics.status_code, 200)
        content = r_metrics.text

        # Verify core operational metrics are properly exposed
        self.assertIn("pos_igpu_vram_free_bytes", content)
        self.assertIn("pos_checkout_scanner_rate_hz", content)
        self.assertIn("kan_routing_decision_total", content)

if __name__ == "__main__":
    unittest.main()

