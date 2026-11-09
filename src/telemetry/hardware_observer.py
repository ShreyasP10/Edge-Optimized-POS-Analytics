import time
import psutil
from src.config import settings

class HardwareObserver:
    """
    Monitors edge POS terminal APU health, shared VRAM usage, and die temperatures.
    Provides normalized telemetry vectors for the KAN gating layer.
    """

    def __init__(self, vram_total_mb: float = None):
        self.vram_total_mb = vram_total_mb or settings.VRAM_TOTAL_MB
        self._simulated_vram_free_mb = self.vram_total_mb * 0.82
        self._simulated_die_temp_c = 52.0

    def get_vram_metrics(self) -> dict:
        """
        Samples available VRAM. On APU architectures, VRAM is dynamically
        allocated from system RAM. Uses available physical memory as a proxy
        when direct GPU queries are not accessible.
        """
        try:
            mem = psutil.virtual_memory()
            free_mb = mem.available / (1024 * 1024)
            # Bound within the configured APU UMA aperture
            effective_vram_free = min(free_mb, self.vram_total_mb)
        except Exception:
            effective_vram_free = self._simulated_vram_free_mb

        ratio = max(0.0, min(1.0, effective_vram_free / self.vram_total_mb))
        return {
            "vram_total_mb": self.vram_total_mb,
            "vram_free_mb": round(effective_vram_free, 1),
            "vram_free_ratio": round(ratio, 4)
        }

    def get_cpu_and_thermal(self) -> dict:
        """
        Samples CPU load and estimated APU die temperature.
        """
        cpu_pct = psutil.cpu_percent(interval=None)
        
        # Try reading real hardware temperature sensors if supported by OS
        die_temp_c = self._simulated_die_temp_c
        try:
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            die_temp_c = entries[0].current
                            break
        except Exception:
            pass

        # Normalized thermal headroom: (85°C - T) / (85 - 40)
        thermal_headroom = max(0.0, min(1.0, (85.0 - die_temp_c) / (85.0 - 40.0)))
        return {
            "cpu_utilization_pct": round(cpu_pct, 1),
            "die_temp_celsius": round(die_temp_c, 1),
            "thermal_headroom_ratio": round(thermal_headroom, 4)
        }

    def sample_state(self) -> dict:
        """
        Returns a complete hardware telemetry snapshot.
        """
        vram = self.get_vram_metrics()
        thermal = self.get_cpu_and_thermal()
        return {
            "timestamp": time.time(),
            **vram,
            **thermal
        }

hardware_observer = HardwareObserver()

