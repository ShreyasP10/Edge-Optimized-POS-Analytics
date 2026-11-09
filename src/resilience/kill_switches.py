import os
import threading
from typing import Dict, Any

class KillSwitchManager:
    """
    Manages runtime operational feature flags, emergency kill switches,
    and graceful degradation modes without requiring process restarts.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._switches = {
            "READ_ONLY_MODE": os.getenv("KILL_SWITCH_READ_ONLY", "false").lower() == "true",
            "KILL_LOCAL_INFERENCE": os.getenv("KILL_LOCAL_INFERENCE", "false").lower() == "true",
            "KILL_CLOUD_FALLBACK": os.getenv("KILL_CLOUD_FALLBACK", "false").lower() == "true",
            "SHED_HEAVY_PAYLOADS": os.getenv("KILL_SHED_HEAVY", "false").lower() == "true",
            "DRAIN_MODE": os.getenv("KILL_DRAIN_MODE", "false").lower() == "true",
        }
        self._cached_fallbacks: Dict[str, Any] = {
            "footfall_estimation": {"footfall_delta": 1, "current_occupancy": 15, "cached": True},
            "dwell_time": {"average_dwell_sec": 35.0, "cached": True},
            "heatmapping": {"density_index": 0.45, "cached": True}
        }

    def is_active(self, flag_name: str) -> bool:
        """Checks if a kill switch is engaged."""
        with self._lock:
            return self._switches.get(flag_name, False)

    def set_switch(self, flag_name: str, enabled: bool):
        """Sets a feature kill switch dynamically."""
        with self._lock:
            self._switches[flag_name] = enabled

    def get_all_switches(self) -> Dict[str, bool]:
        """Returns the current state of all kill switches."""
        with self._lock:
            return dict(self._switches)

    def get_cached_fallback(self, task_type: str) -> dict:
        """Returns a safe, pre-calculated cached response when inference is degraded."""
        with self._lock:
            return self._cached_fallbacks.get(
                task_type,
                {"status": "DEGRADED_FALLBACK", "cached": True}
            )

kill_switch_manager = KillSwitchManager()
