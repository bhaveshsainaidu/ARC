"""
core/self_check.py — Startup Self-Check & Diagnostics for ARC.

Runs a fast, local inspection of hardware, software, configuration, and connectivity.
Guaranteed never to print, log, or leak API keys, tokens, or memory contents.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any

from core import audio_devices
from core.action_loader import discover_actions
from core.plugin_loader import discover_plugins


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def check_api_key(config_path: Path) -> dict[str, Any]:
    """Verify Gemini API key presence and format without revealing it."""
    if not config_path.exists():
        return {
            "status": "MISSING",
            "message": "Configuration file not found (config/api_keys.json)",
            "ready": False
        }
    try:
        from memory.config_manager import load_api_keys
        data = load_api_keys()
        key = str(data.get("gemini_api_key", "")).strip()
        if not key:
            return {
                "status": "NOT_SET",
                "message": "Gemini API key is empty or unset",
                "ready": False
            }
        if len(key) < 20:
            return {
                "status": "INVALID_FORMAT",
                "message": "Gemini API key is suspiciously short (<20 chars)",
                "ready": False
            }
        if not key.startswith("AIza"):
            return {
                "status": "CONFIGURED",
                "message": f"API key configured ({len(key)} chars)",
                "ready": True
            }
        return {
            "status": "CONFIGURED",
            "message": f"API key configured ({len(key)} chars, valid Google AI format)",
            "ready": True
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Failed to parse config: {e}",
            "ready": False
        }


def check_audio() -> dict[str, Any]:
    """Check microphone and speaker availability."""
    try:
        inputs = audio_devices.list_devices("input", refresh=False)
        outputs = audio_devices.list_devices("output", refresh=False)
        
        in_ok = len(inputs) > 0
        out_ok = len(outputs) > 0

        details = []
        if not in_ok:
            details.append("No active microphone found")
        else:
            details.append(f"{len(inputs)} microphone(s) available")

        if not out_ok:
            details.append("No active speaker/audio output found")
        else:
            details.append(f"{len(outputs)} audio output(s) available")

        input_names = [str(d) for d in inputs[:3]]
        output_names = [str(d) for d in outputs[:3]]

        return {
            "ready": in_ok and out_ok,
            "inputs_count": len(inputs),
            "outputs_count": len(outputs),
            "input_names": input_names,
            "output_names": output_names,
            "message": "; ".join(details)
        }
    except Exception as e:
        return {
            "ready": False,
            "inputs_count": 0,
            "outputs_count": 0,
            "message": f"Audio subsystem error: {e}"
        }


def check_internet(host: str = "generativelanguage.googleapis.com", port: int = 443, timeout: float = 2.5) -> dict[str, Any]:
    """Test DNS and TCP connection to Gemini API endpoint."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return {
            "ready": True,
            "host": host,
            "message": f"Connected to {host}:{port} successfully"
        }
    except socket.gaierror:
        return {
            "ready": False,
            "host": host,
            "message": f"DNS resolution failed for {host} (no internet connection)"
        }
    except (socket.timeout, OSError) as e:
        return {
            "ready": False,
            "host": host,
            "message": f"Connection to {host}:{port} timed out or failed: {e}"
        }


def check_browser_engine() -> dict[str, Any]:
    """Check Playwright installation and browser binaries."""
    has_playwright = importlib.util.find_spec("playwright") is not None
    if not has_playwright:
        return {
            "ready": False,
            "installed": False,
            "message": "Playwright package not installed"
        }
    # Check if playwright chromium exists or can be found
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
            exists = Path(chromium_path).exists() if chromium_path else False
            return {
                "ready": exists,
                "installed": True,
                "chromium_path": str(chromium_path) if exists else "Missing",
                "message": "Playwright Chromium is available" if exists else "Playwright installed, but Chromium binary missing (run 'playwright install chromium')"
            }
    except Exception as e:
        return {
            "ready": False,
            "installed": True,
            "message": f"Playwright browser check warning: {e}"
        }


def check_actions_and_plugins(base_dir: Path) -> dict[str, Any]:
    """Discover actions and plugins to verify they import cleanly."""
    actions_dir = base_dir / "actions"
    plugins_dir = base_dir / "plugins"

    errors = []
    actions_count = 0
    plugins_count = 0

    try:
        act_reg = discover_actions(actions_dir, logger=lambda m: None)
        actions_count = len(act_reg.names())
        for r in getattr(act_reg, "_all_records", []):
            if not r.valid and r.error:
                errors.append(f"Action '{r.name}': {r.error}")
    except Exception as e:
        errors.append(f"Action discovery crashed: {e}")

    try:
        plug_reg = discover_plugins(plugins_dir, logger=lambda m: None)
        plugins_count = len(getattr(plug_reg, "_plugins", {}))
    except Exception as e:
        errors.append(f"Plugin discovery crashed: {e}")

    return {
        "ready": actions_count > 0,
        "actions_count": actions_count,
        "plugins_count": plugins_count,
        "errors": errors,
        "message": f"{actions_count} action(s) loaded, {plugins_count} plugin(s) found"
    }


def check_memory(base_dir: Path) -> dict[str, Any]:
    """Verify memory directory and long_term.json accessibility without modifying it."""
    mem_file = base_dir / "memory" / "long_term.json"
    if not mem_file.exists():
        return {
            "ready": True,
            "status": "NEW_USER",
            "message": "Memory store will be initialized upon first conversation"
        }
    try:
        raw = mem_file.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            categories = list(parsed.keys())
            total_keys = sum(len(v) for v in parsed.values() if isinstance(v, dict))
            return {
                "ready": True,
                "status": "VALID",
                "message": f"Memory store healthy ({len(categories)} categories, {total_keys} remembered items)"
            }
        else:
            return {
                "ready": False,
                "status": "CORRUPTED",
                "message": "Memory file does not contain a valid JSON object"
            }
    except Exception as e:
        return {
            "ready": False,
            "status": "ERROR",
            "message": f"Memory file read error: {e}"
        }


def run_self_check(base_dir: Optional[Path] = None) -> dict[str, Any]:
    """Run all self-checks and return a comprehensive summary dictionary."""
    base = base_dir or get_base_dir()
    config_path = base / "config" / "api_keys.json"

    api = check_api_key(config_path)
    audio = check_audio()
    net = check_internet()
    browser = check_browser_engine()
    actions = check_actions_and_plugins(base)
    memory = check_memory(base)

    all_ready = api["ready"] and audio["ready"] and net["ready"] and actions["ready"] and memory["ready"]
    overall_status = "READY" if all_ready else "ATTENTION_REQUIRED"

    return {
        "status": overall_status,
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "checks": {
            "api_key": api,
            "audio": audio,
            "internet": net,
            "browser": browser,
            "actions": actions,
            "memory": memory,
        }
    }


def format_self_check_report(result: dict[str, Any]) -> str:
    """Format the self check result as a clean, human-readable terminal/HUD report."""
    lines = [
        "═══════════════════════════════════════════════════════════════",
        f"  ARC — SYSTEM SELF-CHECK [{result['status']}]",
        "═══════════════════════════════════════════════════════════════",
        f"Platform: {result['platform']} | Python: {result['python_version']}",
        "───────────────────────────────────────────────────────────────",
    ]
    checks = result.get("checks", {})

    def icon(ready: bool) -> str:
        return "✔" if ready else "✖"

    api = checks.get("api_key", {})
    lines.append(f"[{icon(api.get('ready', False))}] API Configuration : {api.get('message', '')}")

    audio = checks.get("audio", {})
    lines.append(f"[{icon(audio.get('ready', False))}] Audio Devices     : {audio.get('message', '')}")

    net = checks.get("internet", {})
    lines.append(f"[{icon(net.get('ready', False))}] Gemini Connectivity: {net.get('message', '')}")

    act = checks.get("actions", {})
    lines.append(f"[{icon(act.get('ready', False))}] Action Discovery  : {act.get('message', '')}")

    mem = checks.get("memory", {})
    lines.append(f"[{icon(mem.get('ready', False))}] Local Memory Store: {mem.get('message', '')}")

    br = checks.get("browser", {})
    lines.append(f"[{icon(br.get('ready', False))}] Browser Automation: {br.get('message', '')}")

    lines.append("═══════════════════════════════════════════════════════════════")
    if result['status'] == "READY":
        lines.append("ARC is fully primed and ready for voice interaction.")
    else:
        lines.append("Please resolve the items marked with [✖] before launching.")
    lines.append("═══════════════════════════════════════════════════════════════")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    report = run_self_check()
    print(format_self_check_report(report))
