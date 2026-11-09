import unittest
import time
import os
import tempfile
from fastapi.testclient import TestClient

from src.resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenException
from src.resilience.rate_limiter import RateLimiter
from src.resilience.kill_switches import KillSwitchManager
from src.resilience.idempotency import IdempotencyManager
from src.resilience.load_leveler import QueueLoadLeveler
from src.resilience.retry_policy import execute_with_retry
from src.storage.sqlite_store import SQLiteStore
from src.main import app

class TestResilienceAndReliability(unittest.TestCase):
    """
    Automated verification of enterprise resilience, rate limiting,
    circuit breakers, backups & restore drills, and idempotency.
    """

    # --- 1. CIRCUIT BREAKER STATE MACHINE ---
    def test_circuit_breaker_lifecycle(self):
        cb = CircuitBreaker("test_cb", failure_threshold=2, recovery_timeout_sec=0.2, half_open_success_threshold=1)
        self.assertEqual(cb.state, CircuitState.CLOSED)

        # Failure 1: Remains CLOSED
        cb._on_failure(ValueError("Error 1"))
        self.assertEqual(cb.state, CircuitState.CLOSED)

        # Failure 2: Trips to OPEN
        cb._on_failure(ValueError("Error 2"))
        self.assertEqual(cb.state, CircuitState.OPEN)

        # While OPEN, call raises or triggers fallback
        fallback_called = False
        def fallback_fn():
            nonlocal fallback_called
            fallback_called = True
            return "FALLBACK_VALUE"

        res = cb.call(lambda: "NORMAL", fallback=fallback_fn)
        self.assertTrue(fallback_called)
        self.assertEqual(res, "FALLBACK_VALUE")

        # Wait for recovery timeout -> transitions to HALF_OPEN
        time.sleep(0.25)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Successful trial call restores to CLOSED
        res_trial = cb.call(lambda: "TRIAL_SUCCESS")
        self.assertEqual(res_trial, "TRIAL_SUCCESS")
        self.assertEqual(cb.state, CircuitState.CLOSED)

    # --- 2. TOKEN-BUCKET RATE LIMITER & QUOTAS ---
    def test_rate_limiter_burst_and_retry_after(self):
        limiter = RateLimiter(rate_per_sec=5.0, burst_capacity=3, daily_quota=10)

        # Consume all 3 burst tokens
        ok1, _ = limiter.is_allowed("client-1", cost=1)
        ok2, _ = limiter.is_allowed("client-1", cost=1)
        ok3, _ = limiter.is_allowed("client-1", cost=1)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertTrue(ok3)

        # 4th request must be rate-limited
        ok4, meta4 = limiter.is_allowed("client-1", cost=1)
        self.assertFalse(ok4)
        self.assertEqual(meta4["reason"], "RATE_LIMIT_EXCEEDED")
        self.assertGreaterEqual(meta4["retry_after_sec"], 1)

    # --- 3. IDEMPOTENCY KEY REPLAY PROTECTION ---
    def test_idempotency_cache_and_deduplication(self):
        manager = IdempotencyManager(ttl_sec=60.0)
        key = "idem-test-key-999"

        # 1. Initial attempt -> NEW
        st1, cached1 = manager.get_or_create(key)
        self.assertEqual(st1, "NEW")
        self.assertIsNone(cached1)

        # 2. In-flight attempt before completion -> IN_PROGRESS
        st2, cached2 = manager.get_or_create(key)
        self.assertEqual(st2, "IN_PROGRESS")

        # 3. Complete initial task
        payload = {"task_id": "uuid-1234", "result": "OK"}
        manager.complete(key, payload)

        # 4. Subsequent replay -> HIT with cached payload
        st3, cached3 = manager.get_or_create(key)
        self.assertEqual(st3, "HIT")
        self.assertEqual(cached3, payload)

    # --- 4. KILL SWITCHES & READ-ONLY DEGRADATION ---
    def test_kill_switches(self):
        ks = KillSwitchManager()
        self.assertFalse(ks.is_active("READ_ONLY_MODE"))

        ks.set_switch("READ_ONLY_MODE", True)
        self.assertTrue(ks.is_active("READ_ONLY_MODE"))

        fallback = ks.get_cached_fallback("footfall_estimation")
        self.assertTrue(fallback.get("cached", False))

    # --- 5. EXPONENTIAL BACKOFF + JITTER ---
    def test_exponential_backoff_retry(self):
        call_count = 0
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionResetError("Transient network drop")
            return "SUCCESS"

        result = execute_with_retry(flaky_func, max_retries=4, base_delay_sec=0.02, max_delay_sec=0.1)
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(call_count, 3)

    # --- 6. HOT BACKUP & RESTORE DRILL ---
    def test_hot_backup_and_restore_verification_drill(self):
        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_store.db")
        store = SQLiteStore(db_path=db_path)

        # Insert test records
        for i in range(5):
            store.record_event(
                event_id=f"evt-{i}",
                task_type="footfall_estimation",
                routing_decision="LOCAL_IGPU",
                kan_score=0.8,
                kan_formula="score = 0.85*V",
                payload_size_mb=10.0,
                execution_time_ms=100.0,
                incurred_cost_usd=0.0,
                telemetry_snapshot={}
            )

        # Execute Online Backup
        backup_path, checksum, count = store.create_online_backup(backup_dir=temp_dir)
        self.assertTrue(os.path.exists(backup_path))
        self.assertEqual(count, 5)
        self.assertEqual(len(checksum), 64)  # SHA-256 hex length

        # Execute Restore Drill
        drill = store.verify_restore_drill(backup_path)
        self.assertEqual(drill["restore_status"], "SUCCESS")
        self.assertEqual(drill["integrity_check"], "ok")
        self.assertEqual(drill["restored_row_count"], 5)

    # --- 7. QUEUE LOAD LEVELER LOAD-SHEDDING ---
    def test_queue_load_leveler_shedding(self):
        leveler = QueueLoadLeveler(max_capacity=3, num_workers=0)  # Zero workers so queue fills up

        # Fill queue to max capacity
        self.assertTrue(leveler.enqueue("t1", {}, lambda d: None, priority=2))
        self.assertTrue(leveler.enqueue("t2", {}, lambda d: None, priority=2))
        self.assertTrue(leveler.enqueue("t3", {}, lambda d: None, priority=2))

        # 4th task must be dropped via load-shedding
        self.assertFalse(leveler.enqueue("t4", {}, lambda d: None, priority=3))
        metrics = leveler.get_metrics()
        self.assertEqual(metrics["total_shedded"], 1)

if __name__ == "__main__":
    unittest.main()
