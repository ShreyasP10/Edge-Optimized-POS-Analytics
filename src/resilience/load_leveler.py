import time
import queue
import threading
import logging
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("resilience.load_leveler")

@dataclass(order=True)
class QueuedAnalyticsTask:
    priority: int  # 1 (Highest: Checkout queue / theft), 2 (Medium: Footfall), 3 (Low: Heatmap)
    timestamp: float = field(compare=False)
    task_id: str = field(compare=False)
    task_data: dict = field(compare=False)
    handler: Callable = field(compare=False)

class QueueLoadLeveler:
    """
    Queue-based load leveler with priority shedding for spike absorption.
    Buffers incoming camera tasks during traffic surges, leveling the processing load
    so the APU memory bandwidth and CPU cycles never spike and impact POS checkout.
    """

    def __init__(self, max_capacity: int = 100, num_workers: int = 1):
        self.max_capacity = max_capacity
        self.num_workers = num_workers
        self._queue = queue.PriorityQueue(maxsize=max_capacity)
        self._running = False
        self._workers = []
        self._dropped_count = 0
        self._processed_count = 0
        self._lock = threading.Lock()

    def start(self):
        """Starts background worker threads for leveled execution."""
        self._running = True
        for i in range(self.num_workers):
            t = threading.Thread(target=self._worker_loop, name=f"LoadLevelerWorker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    def stop(self):
        """Gracefully stops queue workers."""
        self._running = False

    def enqueue(self, task_id: str, task_data: dict, handler: Callable, priority: int = 2) -> bool:
        """
        Enqueues an analytics task for leveled processing.
        If the queue is full, sheds load (drops lowest-priority task or rejects).
        """
        item = QueuedAnalyticsTask(
            priority=priority,
            timestamp=time.time(),
            task_id=task_id,
            task_data=task_data,
            handler=handler
        )
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            with self._lock:
                self._dropped_count += 1
            logger.warning(f"Load Leveler Queue FULL ({self.max_capacity}). Shedding task {task_id}.")
            return False

    def _worker_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
                try:
                    item.handler(item.task_data)
                    with self._lock:
                        self._processed_count += 1
                except Exception as e:
                    logger.error(f"Error processing leveled task {item.task_id}: {e}")
                finally:
                    self._queue.task_done()
            except queue.Empty:
                continue

    def get_metrics(self) -> dict:
        """Returns queue depth and load-shedding metrics."""
        with self._lock:
            return {
                "current_queue_depth": self._queue.qsize(),
                "max_capacity": self.max_capacity,
                "total_processed": self._processed_count,
                "total_shedded": self._dropped_count,
                "queue_utilization_pct": round((self._queue.qsize() / self.max_capacity) * 100, 1)
            }

queue_load_leveler = QueueLoadLeveler(max_capacity=100, num_workers=1)
