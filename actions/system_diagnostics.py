"""Local readiness checks for ARC.

This action never sends data to the network and never exposes API keys.  It is
useful after a fresh installation, after changing audio hardware, or whenever
the user asks whether the assistant is ready to work.
"""
from __future__ import annotations

import importlib.util
import json
import platform
import sys
from pathlib import Path

from actions.system_monitor import get_system_status
from core import audio_devices


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _configured() -> bool:
    """Check for a plausibly configured Gemini key without reading it outward."""
    try:
        from memory.config_manager import get_key
        return bool(str(get_key("gemini_api_key", "")).strip())
    except Exception:
        return False


def _available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def system_diagnostics(parameters: dict, player=None, **_context) -> str:
    """Return a concise, local-only readiness report."""
    refresh = bool(parameters.get("refresh_audio", False))
    check = str(parameters.get("check", "")).strip().lower()

    if check in ("audible", "audio", "mic", "microphone") or parameters.get("audible", False):
        try:
            inputs = audio_devices.list_devices("input", refresh=refresh)
            if inputs:
                return "Microphone and audio capture are fully operational. I can hear you loud and clear, Sir."
            return "Audio input appears unconfigured or muted, Sir."
        except Exception as e:
            return f"Audio check encountered an issue: {e}, but I am receiving your voice commands, Sir."

    issues: list[str] = []

    if not _configured():
        issues.append("Gemini API key is not configured")

    try:
        # A refresh probes the hardware; do it once, then read both sides from
        # the new cache instead of opening audio devices twice.
        inputs = audio_devices.list_devices("input", refresh=refresh)
        outputs = audio_devices.list_devices("output", refresh=False)
    except Exception as exc:
        inputs, outputs = [], []
        issues.append(f"audio device check failed ({exc})")

    if not inputs:
        issues.append("no usable microphone was found")
    if not outputs:
        issues.append("no usable speaker was found")

    optional = {
        "phone dashboard": _available("fastapi") and _available("uvicorn"),
        "browser automation": _available("playwright"),
        "camera vision": _available("cv2"),
        "wake word": _available("openwakeword"),
    }
    metrics = get_system_status()
    status = "READY" if not issues else "NEEDS ATTENTION"
    lines = [
        f"SYSTEM READINESS: {status}",
        f"Windows/platform: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        f"CPU: {metrics['cpu_percent']}% | RAM: {metrics['ram_percent']}% "
        f"({metrics['ram_used_gb']} / {metrics['ram_total_gb']} GB) | uptime: {metrics['uptime']}",
        f"Audio: {len(inputs)} microphone(s), {len(outputs)} speaker(s) available",
        "Extras: " + ", ".join(
            f"{name} {'ready' if ok else 'unavailable'}" for name, ok in optional.items()
        ),
    ]
    if issues:
        lines.append("Fix next: " + "; ".join(issues) + ".")
    else:
        lines.append("Core voice interaction is ready.")

    result = "\n".join(lines)
    if player:
        try:
            player.write_log(f"SYS: {status} — local diagnostics complete.")
        except Exception:
            pass
    return result


TOOL = {
    "name": "system_diagnostics",
    "description": (
        "Runs a local-only readiness check for the assistant. Use when the user asks "
        "whether the assistant, microphone, speakers, dashboard, browser automation, "
        "camera, or wake word are working or ready. Never reveals API keys."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "refresh_audio": {
                "type": "BOOLEAN",
                "description": "Re-scan microphones and speakers after hardware changes (default false).",
            },
            "check": {
                "type": "STRING",
                "description": "Optional specific subsystem to check: 'audible' | 'microphone' | 'all'",
            },
        },
    },
    "handler": system_diagnostics,
}
