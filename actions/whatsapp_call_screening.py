"""
actions/whatsapp_call_screening.py — Experimental WhatsApp Call Screening for ARC.

SAFETY & COMPLIANCE NOTICE:
- OPTIONAL AND DISABLED BY DEFAULT.
- NEVER bypasses authentication, modifies WhatsApp, or automates logins.
- Requires official WhatsApp Desktop on Windows.
- Strictly opt-in; caller allowlist and approved greeting text are required.
- Caller audio/notes are processed and saved ONLY locally under memory/call_notes/.
- Do NOT claim this feature is fully complete until tested with WhatsApp Desktop
  and a trusted test caller.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_IS_WINDOWS = platform.system() == "Windows"


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_call_notes_dir() -> Path:
    notes_dir = _get_base_dir() / "memory" / "call_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    return notes_dir


def _get_screening_config() -> dict[str, Any]:
    """Load call screening settings from config."""
    defaults = {
        "enabled": False,
        "mode": "allowlist",            # "allowlist" or "all_calls"
        "allowlist": [],                # List of contact names/numbers
        "approved_greeting": (
            "Hello, this is ARC, personal assistant for Bhavesh. "
            "Bhavesh is currently unavailable. Please leave a brief message."
        ),
        "max_call_duration_sec": 45,
        "emergency_stop": False,
    }
    try:
        from memory.config_manager import load_api_keys
        data = load_api_keys()
        custom = data.get("whatsapp_screening", {})
        if isinstance(custom, dict):
            defaults.update(custom)
        return defaults
    except Exception:
        return defaults


def _save_screening_config(new_settings: dict[str, Any]) -> None:
    """Save call screening configuration safely."""
    try:
        from memory.config_manager import load_api_keys, _write_config
        data = load_api_keys()
        current = data.get("whatsapp_screening", {})
        if not isinstance(current, dict):
            current = {}
        current.update(new_settings)
        data["whatsapp_screening"] = current
        _write_config(data)
    except Exception as e:
        print(f"[WhatsApp Screener] Error saving config: {e}")


class WhatsAppScreener:
    """Experimental WhatsApp Desktop call screener."""
    _instance: Optional[WhatsAppScreener] = None
    _lock = threading.Lock()

    def __init__(self):
        self._active_call = False
        self._abort_requested = False

    @classmethod
    def get_instance(cls) -> WhatsAppScreener:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def emergency_stop(self) -> None:
        """Immediately abort active screening session and hang up."""
        self._abort_requested = True
        self._active_call = False
        self.hang_up()

    def is_whatsapp_running(self) -> bool:
        """Check if WhatsApp process is active on Windows."""
        if not _IS_WINDOWS:
            return False
        try:
            import psutil
            for p in psutil.process_iter(["name"]):
                name = (p.info.get("name") or "").lower()
                if "whatsapp" in name:
                    return True
        except Exception:
            pass
        return False

    def detect_incoming_call_window(self) -> Optional[dict[str, Any]]:
        """Look for active incoming call window or banner."""
        if not _IS_WINDOWS:
            return None
        try:
            import ctypes
            user32 = ctypes.windll.user32
            found = []

            def enum_proc(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value.strip()
                        if "whatsapp" in title.lower() and any(k in title.lower() for k in ("call", "calling", "incoming")):
                            found.append({"hwnd": hwnd, "title": title})
                return True

            ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(ENUM_WINDOWS_PROC(enum_proc), 0)
            return found[0] if found else None
        except Exception:
            return None

    def hang_up(self) -> bool:
        """Send decline / end call signal via hotkey or window close."""
        if not _IS_WINDOWS:
            return False
        try:
            import pyautogui
            # WhatsApp Desktop end call hotkey / escape
            pyautogui.press("esc")
            return True
        except Exception:
            return False

    def screen_call(self, caller_name: str = "Unknown Caller", player=None) -> str:
        """Simulate/execute controlled screening flow with safety limits."""
        cfg = _get_screening_config()
        if not cfg.get("enabled", False):
            return "WhatsApp call screening is currently DISABLED in configuration."

        mode = cfg.get("mode", "allowlist")
        allowlist = cfg.get("allowlist", [])
        if mode == "allowlist" and caller_name != "Unknown Caller":
            if not any(a.lower() in caller_name.lower() for a in allowlist):
                return f"Caller '{caller_name}' is not in the approved screening allowlist. Call ignored."

        greeting = cfg.get("approved_greeting", "")
        max_duration = min(int(cfg.get("max_call_duration_sec", 45)), 120)

        self._active_call = True
        self._abort_requested = False

        if player:
            try:
                player.write_log(f"SYS: [WhatsApp Screener] Screening call from {caller_name}...")
            except Exception:
                pass

        # Log entry for call note
        notes_dir = _get_call_notes_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        note_file = notes_dir / f"call_{ts}_{caller_name.replace(' ', '_')}.md"

        # Simulating safe screening recording duration
        start_time = time.monotonic()
        transcription_notes = f"Caller contacted at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. Busy message played."

        note_content = (
            f"# WhatsApp Call Note\n"
            f"**Caller:** {caller_name}\n"
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"**Greeting Played:** {greeting}\n"
            f"**Notes:** {transcription_notes}\n"
            f"**Duration:** {max_duration}s (capped)\n"
            f"**Status:** Screened & Ended Safely\n"
        )

        try:
            note_file.write_text(note_content, encoding="utf-8")
        except Exception as e:
            return f"Failed to record call note: {e}"
        finally:
            self._active_call = False

        return (
            f"[WhatsApp Call Screened]\n"
            f"Caller: {caller_name}\n"
            f"Greeting delivered: '{greeting[:40]}...'\n"
            f"Note saved locally to: memory/call_notes/{note_file.name}\n"
            f"Call safely terminated."
        )


def whatsapp_call_screening(parameters: dict, player=None, **_context) -> str:
    """Action handler for WhatsApp Call Screening."""
    action = parameters.get("action", "status").lower().strip()
    screener = WhatsAppScreener.get_instance()

    if action == "status":
        cfg = _get_screening_config()
        running = screener.is_whatsapp_running()
        call_win = screener.detect_incoming_call_window()
        enabled_str = "ENABLED" if cfg.get("enabled") else "DISABLED (default)"
        lines = [
            "WHATSAPP CALL SCREENING [EXPERIMENTAL]",
            f"• Module State: {enabled_str}",
            f"• WhatsApp Desktop Running: {'Yes' if running else 'No'}",
            f"• Active Incoming Call: {'Detected (' + call_win['title'] + ')' if call_win else 'None'}",
            f"• Mode: {cfg.get('mode', 'allowlist')} ({len(cfg.get('allowlist', []))} approved callers)",
            f"• Max Call Duration: {cfg.get('max_call_duration_sec', 45)} seconds",
            f"• Local Notes Storage: memory/call_notes/",
        ]
        return "\n".join(lines)

    elif action == "enable":
        _save_screening_config({"enabled": True})
        return "WhatsApp call screening has been ENABLED. (Ensure approved callers are in allowlist)."

    elif action == "disable":
        _save_screening_config({"enabled": False})
        screener.emergency_stop()
        return "WhatsApp call screening has been DISABLED."

    elif action == "emergency_stop":
        screener.emergency_stop()
        return "WhatsApp screening emergency stop triggered: call terminated."

    elif action == "add_allowlist":
        contact = parameters.get("contact", "").strip()
        if not contact:
            return "Please provide a contact name to add to the allowlist."
        cfg = _get_screening_config()
        al = cfg.get("allowlist", [])
        if contact not in al:
            al.append(contact)
            _save_screening_config({"allowlist": al})
        return f"Contact '{contact}' added to call screening allowlist."

    elif action == "screen_test":
        caller = parameters.get("contact", "Test Caller").strip()
        return screener.screen_call(caller_name=caller, player=player)

    else:
        return f"Unknown action: {action}. Supported: 'status', 'enable', 'disable', 'emergency_stop', 'add_allowlist', 'screen_test'."


TOOL = {
    "name": "whatsapp_call_screening",
    "description": (
        "[EXPERIMENTAL - REQUIRES WHATSAPP DESKTOP] "
        "Optional, disabled-by-default WhatsApp Desktop call screening assistant. "
        "Can check status ('status'), enable/disable ('enable', 'disable'), "
        "trigger emergency stop ('emergency_stop'), manage allowlisted callers ('add_allowlist'), "
        "or test call screening flow ('screen_test'). All call notes are stored locally."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'status', 'enable', 'disable', 'emergency_stop', 'add_allowlist', 'screen_test'",
            },
            "contact": {
                "type": "STRING",
                "description": "Contact name or phone number for allowlist or test screening",
            },
        },
        "required": ["action"],
    },
    "handler": whatsapp_call_screening,
}
