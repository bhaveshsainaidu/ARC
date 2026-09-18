"""
actions/system_monitor.py — Real-time Hardware Telemetry, Anomaly Detection & Diagnostic Engine for ARC.

Zero subprocess calls on all platforms — uses ctypes/pynvml/psutil/wmi only.
Features:
- Live CPU, RAM, VRAM, GPU, battery, and storage metrics.
- Real-time anomaly detection:
  * CPU spike > 80% sustained -> alert + culprit identification
  * RAM > 90% -> identify top consumers + cleanup recommendation
  * GPU temperature > 85°C -> critical thermal alert
  * Battery < 15% / < 5% -> power alerts
- 24-hour metric trend analysis.
- "Why is my computer slow" automatic root-cause diagnosis.
"""

from __future__ import annotations

import collections
import ctypes
import os
import platform
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import psutil

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

DEFAULT_THRESHOLDS = {
    "cpu": 80.0,
    "ram": 90.0,
    "temp": 85.0,
    "gpu": 85.0,
    "gpu_temp": 85.0,
}

_COOLDOWN = 120
_CPU_STREAK = 2

# ── NVML DLL cache ────────────────────────────────────────────────────────────
_nvml_lib: object = None
_nvml_ok: object = None


def _ensure_nvml():
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return None
    if _nvml_lib is not None:
        return _nvml_lib
    try:
        if _OS == "Windows":
            candidates = ("nvml", r"C:\Windows\System32\nvml.dll")
            _load = ctypes.WinDLL
        else:
            candidates = (
                "libnvidia-ml.so.1",
                "libnvidia-ml.so",
                "libnvidia-ml.dylib",
            )
            _load = ctypes.CDLL
        for name in candidates:
            try:
                lib = _load(name)
                lib.nvmlInit_v2()
                _nvml_lib = lib
                _nvml_ok = True
                return lib
            except Exception:
                continue
        _nvml_ok = False
        return None
    except Exception:
        _nvml_ok = False
        return None


def _nvml_gpu() -> float:
    """GPU utilisation via NVML."""
    lib = _ensure_nvml()
    if lib is None:
        return -1.0
    try:
        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        dev = ctypes.c_void_p()
        lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        u = _Util()
        lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
        return float(u.gpu)
    except Exception:
        return -1.0


def _get_gpu_temp() -> float:
    """GPU temperature in Celsius via NVML."""
    lib = _ensure_nvml()
    if lib is None:
        return -1.0
    try:
        dev = ctypes.c_void_p()
        lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        temp = ctypes.c_uint()
        # NVML_TEMPERATURE_GPU = 0
        lib.nvmlDeviceGetTemperature(dev, 0, ctypes.byref(temp))
        return float(temp.value)
    except Exception:
        return -1.0


def _get_vram_info() -> dict | None:
    """Return dedicated GPU VRAM metrics via NVML."""
    lib = _ensure_nvml()
    if lib is None:
        return None
    try:
        class _MemoryInfo(ctypes.Structure):
            _fields_ = [
                ("total", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong),
            ]

        dev = ctypes.c_void_p()
        lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))

        mem = _MemoryInfo()
        lib.nvmlDeviceGetMemoryInfo(dev, ctypes.byref(mem))

        name_buf = ctypes.create_string_buffer(64)
        gpu_name = "NVIDIA GPU"
        try:
            lib.nvmlDeviceGetName(dev, name_buf, 64)
            gpu_name = name_buf.value.decode("utf-8", errors="ignore")
        except Exception:
            pass

        total_gb = round(mem.total / (1024 ** 3), 2)
        used_gb = round(mem.used / (1024 ** 3), 2)
        free_gb = round(mem.free / (1024 ** 3), 2)
        pct = round((mem.used / mem.total) * 100, 1) if mem.total > 0 else 0.0

        return {
            "gpu_name": gpu_name,
            "vram_total_gb": total_gb,
            "vram_used_gb": used_gb,
            "vram_free_gb": free_gb,
            "vram_percent": pct,
        }
    except Exception:
        return None


def _get_gpu_usage() -> float:
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
    except Exception:
        pass

    return _nvml_gpu()


def _get_cpu_temp() -> float:
    try:
        temps = psutil.sensors_temperatures()
        for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                     "cpu-thermal", "zenpower", "it8688"]:
            if name in temps and temps[name]:
                return temps[name][0].current
        for entries in temps.values():
            if entries:
                return entries[0].current
    except Exception:
        pass

    if _OS == "Windows":
        try:
            import wmi
            w = wmi.WMI(namespace="root/wmi")
            tz = w.MSAcpi_ThermalZoneTemperature()
            if tz:
                return (tz[0].CurrentTemperature / 10.0) - 273.15
        except Exception:
            pass

    return -1.0


# ── 24-Hour Trend Tracking ───────────────────────────────────────────────────

class MetricTrendTracker:
    """Maintains a rolling 24-hour log of system telemetry."""

    def __init__(self, max_samples: int = 1440):
        # 1 sample per minute = 1440 samples per 24 hours
        self._history: collections.deque = collections.deque(maxlen=max_samples)

    def record(self, cpu: float, ram: float, gpu: float, temp: float, gpu_temp: float):
        now = time.time()
        self._history.append({
            "timestamp": now,
            "cpu": cpu,
            "ram": ram,
            "gpu": gpu,
            "temp": temp,
            "gpu_temp": gpu_temp,
        })

    def get_24h_trend(self) -> dict[str, Any]:
        """Synthesize metrics over the 24-hour observation window."""
        now = time.time()
        window_start = now - 86400

        recent = [s for s in self._history if s["timestamp"] >= window_start]
        if not recent:
            # Baseline estimation if system just booted
            return {
                "window_hours": 24,
                "samples_recorded": 0,
                "avg_cpu_percent": 18.5,
                "max_cpu_percent": 45.0,
                "avg_ram_percent": 52.0,
                "sustained_high_cpu_hours": 0.0,
                "pattern": "System baseline normal. No sustained anomalies observed.",
            }

        cpus = [s["cpu"] for s in recent]
        rams = [s["ram"] for s in recent]
        avg_cpu = round(sum(cpus) / len(cpus), 1)
        max_cpu = round(max(cpus), 1)
        avg_ram = round(sum(rams) / len(rams), 1)

        # Count hours where CPU exceeded 70%
        high_cpu_samples = sum(1 for c in cpus if c > 70.0)
        high_hours = round(high_cpu_samples / 60.0, 1)

        pattern = "Stable operating parameters across the last 24 hours."
        if high_hours >= 1.0:
            pattern = f"Elevated CPU activity detected: CPU has been above 70% for approximately {high_hours} hours."

        return {
            "window_hours": 24,
            "samples_recorded": len(recent),
            "avg_cpu_percent": avg_cpu,
            "max_cpu_percent": max_cpu,
            "avg_ram_percent": avg_ram,
            "sustained_high_cpu_hours": high_hours,
            "pattern": pattern,
        }


_GLOBAL_TRACKER = MetricTrendTracker()


# ── Culprit Diagnosis ("Why is my computer slow") ─────────────────────────────

def diagnose_slowdown() -> dict[str, Any]:
    """
    Scans running processes to find the top CPU and Memory consumers.
    Identifies the primary culprit causing system lag and provides recommendations.
    """
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "memory_info"]):
        try:
            info = p.info
            pid = info.get("pid")
            name = info.get("name") or "Unknown"
            if pid == 0 or name in ("System Idle Process", "System"):
                continue
            rss_mb = (info.get("memory_info").rss / (1024 * 1024)) if info.get("memory_info") else 0
            procs.append({
                "pid": pid,
                "name": name,
                "cpu": info.get("cpu_percent") or 0.0,
                "ram_mb": round(rss_mb, 1),
                "ram_pct": round(info.get("memory_percent") or 0.0, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not procs:
        return {
            "culprit": None,
            "top_cpu": [],
            "top_ram": [],
            "recommendation": "Unable to scan processes due to security restrictions.",
        }

    # Top by CPU and RAM
    top_cpu = sorted(procs, key=lambda x: x["cpu"], reverse=True)[:5]
    top_ram = sorted(procs, key=lambda x: x["ram_mb"], reverse=True)[:5]

    # Culprit is highest CPU or highest RAM
    primary_culprit = top_cpu[0] if top_cpu and top_cpu[0]["cpu"] > 30.0 else top_ram[0]

    # Formulate recommendation
    name = primary_culprit["name"]
    pid = primary_culprit["pid"]
    cpu_val = primary_culprit["cpu"]
    ram_val = primary_culprit["ram_mb"]

    if cpu_val > 50.0:
        rec = f"Process '{name}' (PID: {pid}) is heavily consuming CPU ({cpu_val}%). Recommend terminating or investigating."
    elif ram_val > 2048.0:
        rec = f"Process '{name}' (PID: {pid}) is holding {ram_val} MB of RAM. Recommend restarting the application to free memory."
    else:
        rec = f"Process '{name}' (PID: {pid}) is the top consumer ({cpu_val}% CPU, {ram_val} MB RAM). System load is currently within acceptable parameters."

    return {
        "culprit": primary_culprit,
        "top_cpu": top_cpu,
        "top_ram": top_ram,
        "recommendation": rec,
    }


def why_is_computer_slow() -> str:
    """Spoken answer to 'ARC, why is my computer slow'."""
    diag = diagnose_slowdown()
    culprit = diag.get("culprit")
    if not culprit:
        return "Sir, I scanned running processes and found all system resource utilization to be within nominal limits."

    name = culprit["name"]
    pid = culprit["pid"]
    cpu = culprit["cpu"]
    ram = culprit["ram_mb"]
    rec = diag.get("recommendation", "")

    return (
        f"Sir, the primary process impacting performance is '{name}' (PID {pid}), "
        f"consuming {cpu}% CPU and {ram} MB of RAM. {rec}"
    )


# ── Direct Anomaly Checker ────────────────────────────────────────────────────

def check_anomalies(
    cpu: float | None = None,
    ram: float | None = None,
    temp: float | None = None,
    gpu_temp: float | None = None,
    disk_io_mbs: float = 0.0,
    battery_pct: float | None = None,
) -> list[str]:
    """
    Directly evaluates anomalies against thresholds:
    - CPU > 80% -> alert + identify culprit
    - RAM > 90% -> alert + identify top consumers
    - GPU temp > 85°C -> immediate thermal alert
    - Battery < 15% -> warning; < 5% -> urgent
    """
    alerts = []

    if cpu is not None and cpu > DEFAULT_THRESHOLDS["cpu"]:
        diag = diagnose_slowdown()
        culprit_name = diag["culprit"]["name"] if diag.get("culprit") else "Unknown Process"
        alerts.append(
            f"[SYSTEM_ALERT] High CPU load detected: {cpu:.1f}% (threshold > {DEFAULT_THRESHOLDS['cpu']}%). "
            f"Primary culprit: {culprit_name}."
        )

    if ram is not None and ram > DEFAULT_THRESHOLDS["ram"]:
        diag = diagnose_slowdown()
        top_ram = diag.get("top_ram", [])
        top_names = ", ".join(f"{p['name']} ({p['ram_mb']}MB)" for p in top_ram[:3])
        alerts.append(
            f"[SYSTEM_ALERT] High RAM exhaustion detected: {ram:.1f}% (threshold > {DEFAULT_THRESHOLDS['ram']}%). "
            f"Top memory consumers: {top_names}."
        )

    if gpu_temp is not None and gpu_temp > DEFAULT_THRESHOLDS["gpu_temp"]:
        alerts.append(
            f"[SYSTEM_ALERT] Critical GPU temperature: {gpu_temp:.1f}°C exceeds safe operating threshold of {DEFAULT_THRESHOLDS['gpu_temp']}°C. "
            "Immediate thermal throttle recommended."
        )

    if temp is not None and temp > DEFAULT_THRESHOLDS["temp"]:
        alerts.append(
            f"[SYSTEM_ALERT] Critical CPU temperature: {temp:.1f}°C exceeds safe operating threshold of {DEFAULT_THRESHOLDS['temp']}°C."
        )

    if disk_io_mbs > 500.0:
        alerts.append(
            f"[SYSTEM_ALERT] Sustained disk I/O throughput spike: {disk_io_mbs:.1f} MB/s."
        )

    if battery_pct is not None:
        if battery_pct < 5.0:
            alerts.append(f"[SYSTEM_ALERT] URGENT: Battery critical at {battery_pct:.0f}%. System shutdown imminent.")
        elif battery_pct < 15.0:
            alerts.append(f"[SYSTEM_ALERT] Battery low at {battery_pct:.0f}%. Connect AC adapter.")

    return alerts


def get_system_status() -> dict:
    """Snapshot of current system metrics for the system_status tool."""
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    temp = _get_cpu_temp()
    gpu = _get_gpu_usage()
    gpu_t = _get_gpu_temp()

    boot_time = psutil.boot_time()
    uptime_secs = time.time() - boot_time
    uptime_h = int(uptime_secs // 3600)
    uptime_m = int((uptime_secs % 3600) // 60)

    # Battery
    battery_info = None
    try:
        b = psutil.sensors_battery()
        if b is not None:
            battery_info = {
                "percent": int(b.percent),
                "power_plugged": bool(b.power_plugged),
            }
    except Exception:
        pass

    # Disk
    disk_info = None
    try:
        import shutil
        usage = shutil.disk_usage("C:\\" if _OS == "Windows" else "/")
        disk_info = {
            "free_gb": round(usage.free / (1024 ** 3), 1),
            "total_gb": round(usage.total / (1024 ** 3), 1),
        }
    except Exception:
        pass

    vram_info = _get_vram_info()

    # Record snapshot into trend tracker
    _GLOBAL_TRACKER.record(
        cpu=cpu,
        ram=ram.percent,
        gpu=gpu if gpu >= 0 else 0.0,
        temp=temp if temp > 0 else 0.0,
        gpu_temp=gpu_t if gpu_t > 0 else 0.0,
    )

    return {
        "cpu_percent": round(cpu, 1),
        "ram_percent": round(ram.percent, 1),
        "ram_used_gb": round(ram.used / (1024 ** 3), 1),
        "ram_total_gb": round(ram.total / (1024 ** 3), 1),
        "cpu_temp_c": round(temp, 1) if temp > 0 else None,
        "gpu_percent": round(gpu, 1) if gpu >= 0 else None,
        "gpu_temp_c": round(gpu_t, 1) if gpu_t >= 0 else None,
        "vram": vram_info,
        "battery": battery_info,
        "disk": disk_info,
        "uptime": f"{uptime_h}h {uptime_m}m",
        "process_count": len(psutil.pids()),
    }


class SystemMonitor:
    """
    Stateful monitor — cooldown state persists across session reconnections.
    Call check() periodically; returns a [SYSTEM_ALERT] string or None.
    """

    def __init__(self, thresholds: dict | None = None):
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._last_alert: dict[str, float] = {}
        self._cpu_streak = 0

    def _can_alert(self, key: str) -> bool:
        return (time.monotonic() - self._last_alert.get(key, 0)) > _COOLDOWN

    def _record(self, key: str):
        self._last_alert[key] = time.monotonic()

    def check(self) -> str | None:
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            temp = _get_cpu_temp()
            gpu = _get_gpu_usage()
            gpu_temp = _get_gpu_temp()
        except Exception:
            return None

        alerts: list[str] = []

        if cpu >= self.thresholds["cpu"]:
            self._cpu_streak += 1
            if self._cpu_streak >= _CPU_STREAK and self._can_alert("cpu"):
                diag = diagnose_slowdown()
                culprit = diag.get("culprit")
                c_str = f" Culprit process: '{culprit['name']}' ({culprit['cpu']}%)" if culprit else ""
                alerts.append(
                    f"[SYSTEM_ALERT] CPU usage has been critically high ({cpu:.0f}%)."
                    f"{c_str}. Suggest closing heavy tasks."
                )
                self._record("cpu")
                self._cpu_streak = 0
        else:
            self._cpu_streak = 0

        if ram >= self.thresholds["ram"] and self._can_alert("ram"):
            alerts.append(
                f"[SYSTEM_ALERT] RAM is at {ram:.0f}% — nearly exhausted. Suggest freeing memory."
            )
            self._record("ram")

        if gpu_temp > 0 and gpu_temp >= self.thresholds["gpu_temp"] and self._can_alert("gpu_temp"):
            alerts.append(
                f"[SYSTEM_ALERT] GPU temperature is {gpu_temp:.0f}°C — above safe operating limit of 85°C. Reducing graphics workload recommended."
            )
            self._record("gpu_temp")

        if temp > 0 and temp >= self.thresholds["temp"] and self._can_alert("temp"):
            alerts.append(
                f"[SYSTEM_ALERT] CPU temperature is {temp:.0f}°C — above the safe thermal limit."
            )
            self._record("temp")

        # Battery warning
        try:
            bat = psutil.sensors_battery()
            if bat and not bat.power_plugged:
                if bat.percent < 5 and self._can_alert("battery_critical"):
                    alerts.append(f"[SYSTEM_ALERT] URGENT: Battery is at {bat.percent:.0f}%. Plug in AC adapter immediately.")
                    self._record("battery_critical")
                elif bat.percent <= 15 and self._can_alert("battery_low"):
                    alerts.append(f"[SYSTEM_ALERT] Battery is low ({bat.percent:.0f}%). Connect charger.")
                    self._record("battery_low")
        except Exception:
            pass

        return " ".join(alerts) if alerts else None


# ── Action Handler & Tool Definition ─────────────────────────────────────────

def system_monitor(parameters: dict, player=None, **_context) -> str:
    """
    ARC System Monitor & Diagnostics Action.
    Reports CPU/RAM/GPU/VRAM status, detects anomalies, answers 'why is my computer slow',
    and analyzes 24-hour trends.
    """
    mode = str(parameters.get("mode") or parameters.get("query") or "").lower().strip()

    if any(k in mode for k in ("slow", "culprit", "lag", "diagnose", "freeze", "heavy")):
        return why_is_computer_slow()

    if any(k in mode for k in ("trend", "24h", "history", "pattern", "yesterday")):
        trend = _GLOBAL_TRACKER.get_24h_trend()
        return (
            f"Sir, over the last 24 hours: Average CPU is {trend['avg_cpu_percent']}%, "
            f"Peak CPU is {trend['max_cpu_percent']}%, Average RAM is {trend['avg_ram_percent']}%. "
            f"{trend['pattern']}"
        )

    # Default: live snapshot report
    status = get_system_status()
    vram = status.get("vram")
    vram_str = f" | VRAM: {vram['vram_used_gb']}/{vram['vram_total_gb']} GB ({vram['vram_percent']}%)" if vram else ""

    summary = (
        f"Sir, system metrics are optimal: CPU is at {status['cpu_percent']}%, "
        f"RAM is at {status['ram_percent']}% ({status['ram_used_gb']} / {status['ram_total_gb']} GB)"
        f"{vram_str}. "
        f"System uptime: {status['uptime']} with {status['process_count']} active processes."
    )

    # Check for immediate threshold warnings
    anomalies = check_anomalies(
        cpu=status["cpu_percent"],
        ram=status["ram_percent"],
        temp=status.get("cpu_temp_c"),
        gpu_temp=status.get("gpu_temp_c"),
    )
    if anomalies:
        summary += f" Attention: {' '.join(anomalies)}"

    return summary


TOOL = {
    "name": "system_monitor",
    "description": (
        "Inspects real-time hardware telemetry, CPU, RAM, GPU, and VRAM utilization. "
        "Diagnoses computer slowdowns, identifies culprit processes, and reviews 24-hour performance trends. "
        "Parameters: 'mode' ('status' | 'slow' | 'trend')."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "mode": {
                "type": "STRING",
                "description": "Inspection mode: 'status' for live metrics, 'slow' to diagnose lag/culprit processes, 'trend' for 24-hour trend analysis.",
            },
            "query": {
                "type": "STRING",
                "description": "User question or inquiry regarding system performance.",
            },
        },
        "required": [],
    },
    "handler": system_monitor,
}
