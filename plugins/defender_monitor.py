"""
plugins/defender_monitor.py — Windows Defender Event Watcher & Threat Correlation Daemon.

Tails the Windows Defender Operational Event Log in real time using pywin32:
- Channel: "Microsoft-Windows-Windows Defender/Operational"
- Event IDs:
    1006 / 1116: Malware detected
    1007 / 1117: Malware action taken (quarantined/removed)
    1008 / 1118: Malware remediation failed
    2001: Signature update started
    2002: Signature update success
    2003: Signature update failed
    5001: Real-time protection disabled
    5004: Protection configuration altered
    5007: Defender configuration changed / tampering
- Threat Correlation Engine:
    Cross-references Defender alerts with ARC Cyber Shield threat_monitor anomalies.
    Escalates co-incident threats to CRITICAL with combined evidence chains.
"""

from __future__ import annotations

import collections
import datetime
import json
import os
import platform
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_IS_WINDOWS = platform.system() == "Windows"
_WIN32_AVAILABLE = False
if _IS_WINDOWS:
    try:
        import win32evtlog
        import win32evtlogutil
        import win32con
        _WIN32_AVAILABLE = True
    except ImportError:
        _WIN32_AVAILABLE = False


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
SECURITY_DIR = BASE_DIR / "security"
THREAT_DB_PATH = SECURITY_DIR / "threat_db.json"
INCIDENTS_DIR = SECURITY_DIR / "incidents"


# ── Correlation Engine ────────────────────────────────────────────────────────

def _correlate_threat(threat_name: str, resource_path: str) -> Optional[Dict[str, Any]]:
    """Cross-reference a Defender detection with ARC threat_monitor active anomalies."""
    try:
        from plugins.threat_monitor import get_active_threats
        arc_threats = get_active_threats()
    except Exception:
        arc_threats = []

    clean_res = (resource_path or "").lower()
    clean_name = (threat_name or "").lower()

    for at in arc_threats:
        ev_str = " ".join(at.get("evidence", [])).lower()
        sum_str = at.get("summary", "").lower()
        if (clean_res and (clean_res in ev_str or clean_res in sum_str)) or \
           (clean_name and (clean_name in ev_str or clean_name in sum_str)):
            return at
    return None


# ── Defender Monitor Daemon ───────────────────────────────────────────────────

class DefenderMonitorDaemon:
    _instance: Optional[DefenderMonitorDaemon] = None
    _lock = threading.Lock()

    def __init__(self):
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_event_time = time.time()
        self._speak_cb: Optional[Callable[[str], None]] = None
        self._log_cb: Optional[Callable[[str], None]] = None
        self._hud_cb: Optional[Callable[[str, int], None]] = None
        self._recent_event_ids: collections.deque = collections.deque(maxlen=100)
        self._stats = {
            "events_processed": 0,
            "threats_detected": 0,
            "quarantines": 0,
            "failures": 0,
            "correlated": 0,
            "start_time": None,
        }

    @classmethod
    def get_instance(cls) -> DefenderMonitorDaemon:
        with cls._lock:
            if cls._instance is None:
                cls._instance = DefenderMonitorDaemon()
            return cls._instance

    def set_callbacks(
        self,
        speak_cb: Optional[Callable[[str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        hud_cb: Optional[Callable[[str, int], None]] = None,
    ) -> None:
        if speak_cb: self._speak_cb = speak_cb
        if log_cb: self._log_cb = log_cb
        if hud_cb: self._hud_cb = hud_cb

    def is_running(self) -> bool:
        return self._running

    def start(self) -> str:
        with self._lock:
            if self._running:
                return "Defender Monitor is already active."
            self._running = True
            self._stop_event.clear()
            self._stats["start_time"] = datetime.datetime.now().isoformat()
            self._thread = threading.Thread(
                target=self._watch_events,
                name="ARC-DefenderEventWatcher",
                daemon=True,
            )
            self._thread.start()
            return "Windows Defender Event Watcher daemon started."

    def stop(self) -> str:
        with self._lock:
            if not self._running:
                return "Defender Monitor is not running."
            self._running = False
            self._stop_event.set()
            return "Windows Defender Event Watcher daemon stopped."

    def get_status(self) -> Dict[str, Any]:
        return {
            "active": self._running,
            "win32_evtlog_available": _WIN32_AVAILABLE,
            "stats": dict(self._stats),
        }

    # ── Notification Dispatchers ──────────────────────────────────────────────

    def _dispatch_log(self, text: str) -> None:
        try:
            from core.logger import get_logger
            get_logger().system(text)
        except Exception:
            pass

        if self._log_cb:
            try:
                self._log_cb(text)
            except Exception:
                pass
        else:
            print(f"[DefenderMonitor] {text}")

    def _dispatch_event(
        self,
        event_id: int,
        severity: str,
        title: str,
        message: str,
        speech: Optional[str] = None,
    ) -> None:
        self._stats["events_processed"] += 1
        self._dispatch_log(f"🛡️ DEFENDER: [{severity}] {title} — {message}")

        if speech and self._speak_cb:
            try:
                self._speak_cb(speech)
            except Exception as e:
                print(f"[DefenderMonitor] Speech callback failed: {e}")

        if self._hud_cb:
            try:
                # severity level: CRITICAL, HIGH, WARNING, ALL_CLEAR
                self._hud_cb(severity, 1)
            except Exception:
                pass

    # ── Background Event Watcher ──────────────────────────────────────────────

    def _watch_events(self) -> None:
        """Poll the Windows Defender event channel every 5 seconds."""
        channel = "Microsoft-Windows-Windows Defender/Operational"
        last_rec = 0

        while not self._stop_event.is_set():
            if not _WIN32_AVAILABLE:
                self._stop_event.wait(10.0)
                continue

            hand = None
            try:
                hand = win32evtlog.OpenEventLog(None, channel)
            except Exception:
                pass

            if hand:
                try:
                    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
                    events = win32evtlog.ReadEventLog(hand, flags, 0)
                    if events:
                        max_rec = max(e.RecordNumber for e in events)
                        if last_rec == 0:
                            last_rec = max_rec  # Initialize baseline so we don't alert old past events

                        for ev in events:
                            if ev.RecordNumber <= last_rec:
                                break

                            raw_id = ev.EventID & 0x1FFFFFFF
                            strings = ev.StringInserts or []
                            self._handle_defender_event(raw_id, strings)

                        last_rec = max(last_rec, max_rec)
                except Exception as e:
                    pass
                finally:
                    try:
                        win32evtlog.CloseEventLog(hand)
                    except Exception:
                        pass

            self._stop_event.wait(5.0)

    def _handle_defender_event(self, event_id: int, strings: List[str]) -> None:
        """Parse Defender Operational Event IDs and trigger alert pipeline."""
        str_blob = " | ".join(str(s) for s in strings)
        threat_name = strings[1] if len(strings) > 1 else (strings[0] if strings else "Unknown Malware")
        res_path = strings[2] if len(strings) > 2 else ""

        # Check correlation with ARC
        correlated = _correlate_threat(threat_name, res_path)
        if correlated:
            self._stats["correlated"] += 1

        # ── Event 1006 / 1116: Malware Detected ──────────────────────────────
        if event_id in (1006, 1116):
            self._stats["threats_detected"] += 1
            src_str = "Real-Time Protection" if event_id == 1116 else "On-Demand Scan"
            sev = "CRITICAL"
            corr_note = f" [CORRELATED with ARC Threat: {correlated['summary'][:40]}]" if correlated else ""
            msg = f"{threat_name} detected in {res_path} via {src_str}.{corr_note}"
            speech = f"Windows Defender detected {threat_name}. Threat severity is critical. Awaiting your instructions."
            self._dispatch_event(event_id, sev, "MALWARE DETECTED", msg, speech=speech)

        # ── Event 1007 / 1117: Malware Action Taken ──────────────────────────
        elif event_id in (1007, 1117):
            self._stats["quarantines"] += 1
            msg = f"{threat_name} has been quarantined or removed successfully. Path: {res_path}"
            speech = f"Defender has quarantined threat {threat_name}."
            self._dispatch_event(event_id, "HIGH", "THREAT REMEDIATED", msg, speech=speech)

        # ── Event 1008 / 1118: Malware Remediation Failed ────────────────────
        elif event_id in (1008, 1118):
            self._stats["failures"] += 1
            msg = f"Failed to remediate threat {threat_name} at {res_path}! Manual intervention required."
            speech = f"Warning! Windows Defender failed to remediate {threat_name}. Immediate manual action required."
            self._dispatch_event(event_id, "CRITICAL", "REMEDIATION FAILED", msg, speech=speech)

        # ── Event 2001: Signature Update Started ─────────────────────────────
        elif event_id == 2001:
            self._dispatch_log("DEFENDER: Antivirus signature update initiated.")

        # ── Event 2002: Signature Update Succeeded ───────────────────────────
        elif event_id == 2002:
            self._dispatch_log("DEFENDER: Antivirus signatures updated successfully.")
            try:
                if THREAT_DB_PATH.exists():
                    db = json.loads(THREAT_DB_PATH.read_text(encoding="utf-8"))
                    db["defender_signatures_updated"] = datetime.datetime.now().isoformat()
                    THREAT_DB_PATH.write_text(json.dumps(db, indent=2), encoding="utf-8")
            except Exception:
                pass

        # ── Event 2003: Signature Update Failed ──────────────────────────────
        elif event_id == 2003:
            speech = "Defender signature update failed. Attempting manual update."
            self._dispatch_event(
                event_id, "MEDIUM", "SIGNATURE UPDATE FAILED",
                "Microsoft Defender signature update failed.",
                speech=speech
            )
            # Auto-trigger update
            try:
                from actions.defender_control import run_powershell
                threading.Thread(target=lambda: run_powershell("Update-MpSignature"), daemon=True).start()
            except Exception:
                pass

        # ── Event 5001: Real-Time Protection Disabled ────────────────────────
        elif event_id == 5001:
            msg = "WARNING: Real-Time Protection has been DISABLED on this host."
            speech = "Warning. Windows Defender real-time protection has been disabled. Your system is at risk."
            self._dispatch_event(event_id, "HIGH", "REAL-TIME DISABLED", msg, speech=speech)

        # ── Event 5004: Protection Config Changed ────────────────────────────
        elif event_id == 5004:
            self._dispatch_log(f"DEFENDER: Real-time protection configuration updated: {str_blob[:80]}")

        # ── Event 5007: Defender Config Tampered / Changed ───────────────────
        elif event_id == 5007:
            msg = f"Defender configuration modified: {str_blob[:120]}"
            self._dispatch_event(event_id, "HIGH", "CONFIGURATION TAMPER WARNING", msg)


# ── Global API ────────────────────────────────────────────────────────────────

_daemon_instance: Optional[DefenderMonitorDaemon] = None


def get_defender_daemon() -> DefenderMonitorDaemon:
    global _daemon_instance
    if _daemon_instance is None:
        _daemon_instance = DefenderMonitorDaemon.get_instance()
    return _daemon_instance


def start_defender_monitor() -> str:
    return get_defender_daemon().start()


def stop_defender_monitor() -> str:
    return get_defender_daemon().stop()


def get_defender_status() -> Dict[str, Any]:
    return get_defender_daemon().get_status()


def set_defender_callbacks(
    speak_cb: Optional[Callable[[str], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    hud_cb: Optional[Callable[[str, int], None]] = None,
) -> None:
    get_defender_daemon().set_callbacks(speak_cb=speak_cb, log_cb=log_cb, hud_cb=hud_cb)


# ── Plugin Interface ──────────────────────────────────────────────────────────

def run(parameters: dict, **kwargs) -> str:
    action = parameters.get("action", "status")
    if action == "enable":
        return str(start_defender_monitor())
    elif action == "disable":
        return str(stop_defender_monitor())
    else:
        return str(get_defender_status())


PLUGIN = {
    "name": "defender_monitor",
    "description": (
        "Background plugin that watches Windows Defender event log in real time and "
        "alerts ARC immediately when Defender detects, quarantines, or fails to remediate a threat."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["enable", "disable", "status"],
                "description": "Enable, disable, or query defender monitor.",
            }
        },
    },
    "run": run,
}
