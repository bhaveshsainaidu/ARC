"""
core/bandwidth_monitor.py — Real-Time LAN/WAN Bandwidth & Latency Monitor for ARC.

Monitors network latency, packet loss, and connection health to classify
connection into 4 operational tiers:
  - HIGH:     latency < 80ms, loss < 1%
  - MEDIUM:   latency 80-250ms, loss 1-5%
  - LOW:      latency 250-600ms, loss 5-15%
  - CRITICAL: latency > 600ms or packet loss > 15% / unreachable

Allows adaptive quality scaling across audio streaming, dashboard WebSockets,
and screen mirroring.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable, Optional

# Connection states
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
CRITICAL = "CRITICAL"

_current_state: str = HIGH
_current_metrics: dict = {
    "state": HIGH,
    "rtt_ms": 25.0,
    "packet_loss": 0.0,
    "last_updated": time.time(),
}

_callbacks: list[Callable[[str, dict], None]] = []
_lock = threading.Lock()
_monitor_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_forced_state: Optional[str] = None

# Hosts for latency probes (DNS ports - quick non-blocking connect check)
_PROBE_TARGETS = [
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
    ("127.0.0.1", 8000),
]


def _measure_rtt() -> tuple[Optional[float], float]:
    """
    Measures socket connect latency across probe targets.
    Returns (latency_ms, packet_loss_ratio).
    """
    successful_rtts = []
    total_probes = 0

    for host, port in _PROBE_TARGETS[:2]:  # check external DNS probes first
        total_probes += 1
        t0 = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.7)  # 700ms max probe timeout
        try:
            sock.connect((host, port))
            rtt = (time.perf_counter() - t0) * 1000.0
            successful_rtts.append(rtt)
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    if not successful_rtts:
        # If external probes fail, test local loopback/LAN probe
        total_probes += 1
        t0 = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        try:
            sock.connect(("127.0.0.1", 8000))
            rtt = (time.perf_counter() - t0) * 1000.0
            successful_rtts.append(rtt)
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    if not successful_rtts:
        return None, 1.0

    avg_rtt = sum(successful_rtts) / len(successful_rtts)
    loss = (total_probes - len(successful_rtts)) / total_probes
    return avg_rtt, loss


def _classify_state(rtt_ms: Optional[float], loss: float) -> str:
    """Classify bandwidth state based on latency and loss."""
    if rtt_ms is None or loss >= 0.5:
        return CRITICAL
    if rtt_ms > 600.0 or loss > 0.15:
        return CRITICAL
    if rtt_ms > 250.0 or loss > 0.05:
        return LOW
    if rtt_ms > 80.0 or loss > 0.01:
        return MEDIUM
    return HIGH


def _worker_loop() -> None:
    global _current_state, _current_metrics
    while not _stop_event.is_set():
        try:
            rtt, loss = _measure_rtt()
            new_state = _classify_state(rtt, loss)

            with _lock:
                effective_state = _forced_state if _forced_state else new_state
                changed = (effective_state != _current_state)
                _current_state = effective_state
                _current_metrics = {
                    "state": effective_state,
                    "rtt_ms": round(rtt, 1) if rtt is not None else 999.0,
                    "packet_loss": round(loss * 100.0, 1),
                    "last_updated": time.time(),
                }
                metrics_copy = dict(_current_metrics)
                cbs = list(_callbacks)

            if changed:
                for cb in cbs:
                    try:
                        cb(effective_state, metrics_copy)
                    except Exception:
                        pass
        except Exception:
            pass

        _stop_event.wait(3.0)


def get_bandwidth_state() -> str:
    """Returns the current bandwidth classification: HIGH, MEDIUM, LOW, or CRITICAL."""
    with _lock:
        return _forced_state if _forced_state else _current_state


def get_metrics() -> dict:
    """Returns a snapshot dictionary of current network metrics."""
    with _lock:
        return dict(_current_metrics)


def register_callback(fn: Callable[[str, dict], None]) -> None:
    """Register a listener called when bandwidth state or metrics update."""
    with _lock:
        if fn not in _callbacks:
            _callbacks.append(fn)


def set_forced_state(state: Optional[str]) -> None:
    """Override bandwidth state for testing or manual simulation."""
    global _forced_state, _current_state
    with _lock:
        if state in (HIGH, MEDIUM, LOW, CRITICAL, None):
            _forced_state = state
            if state:
                _current_state = state
                _current_metrics["state"] = state
            cbs = list(_callbacks)
            metrics_copy = dict(_current_metrics)
        else:
            return

    for cb in cbs:
        try:
            cb(_current_state, metrics_copy)
        except Exception:
            pass


def start_bandwidth_monitor() -> None:
    """Start background measurement daemon thread."""
    global _monitor_thread
    with _lock:
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _stop_event.clear()
            _monitor_thread = threading.Thread(
                target=_worker_loop,
                name="ARC-BandwidthMonitor",
                daemon=True,
            )
            _monitor_thread.start()


def stop_bandwidth_monitor() -> None:
    """Stop the bandwidth monitor."""
    _stop_event.set()


def get_camera_stream_parameters() -> dict:
    """Returns adaptive camera streaming parameters based on bandwidth state."""
    state = get_bandwidth_state()
    if state == HIGH:
        return {"width": 640, "height": 480, "fps": 30, "quality": 85}
    elif state == MEDIUM:
        return {"width": 480, "height": 360, "fps": 25, "quality": 70}
    elif state == LOW:
        return {"width": 320, "height": 240, "fps": 15, "quality": 50}
    else:  # CRITICAL
        return {"width": 160, "height": 120, "fps": 10, "quality": 35}


# Auto-start monitoring thread on import
start_bandwidth_monitor()

