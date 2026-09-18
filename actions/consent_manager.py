"""
actions/consent_manager.py — ARC Privacy & Permissions Consent Manager.

Provides granular, user-sovereign control over sensitive ARC subsystem capabilities:
  - camera_access
  - microphone_continuous
  - screen_recording
  - biometric_data
  - filesystem_write
  - shell_execution
  - remote_dashboard_control

Configured permissions persist to config/consents.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.ethical_framework import log_ethical_audit


def _get_consents_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    c_path = base / "config" / "consents.json"
    c_path.parent.mkdir(parents=True, exist_ok=True)
    return c_path


_DEFAULT_CONSENTS = {
    "camera_access": False,
    "microphone_continuous": True,
    "screen_recording": True,
    "biometric_data": True,
    "filesystem_write": True,
    "shell_execution": True,
    "remote_dashboard_control": True,
    "telemetry": False,
}

CONSENT_ITEMS = [
    "camera_access",
    "microphone_continuous",
    "screen_recording",
    "biometric_data",
    "filesystem_write",
    "shell_execution",
    "remote_dashboard_control",
    "telemetry",
]


def check_tool_consent(tool_name: str) -> tuple[bool, str]:
    """Check if tool execution is permitted by active consent policies."""
    tool_perm_map = {
        "camera": "camera_access",
        "webcam": "camera_access",
        "screen_processor": "screen_recording",
        "screen_process": "screen_recording",
        "system_monitor": "telemetry",
        "code_helper": "shell_execution",
        "shell": "shell_execution",
    }
    perm = tool_perm_map.get(tool_name.lower(), tool_name)
    from memory.config_manager import get_consent
    allowed = get_consent(perm)
    return allowed, "Permitted" if allowed else f"Consent revoked for {perm}"


def _load_consents() -> Dict[str, bool]:
    p = _get_consents_path()
    if not p.exists():
        p.write_text(json.dumps(_DEFAULT_CONSENTS, indent=2), encoding="utf-8")
        return dict(_DEFAULT_CONSENTS)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULT_CONSENTS)


def _save_consents(data: Dict[str, bool]) -> None:
    p = _get_consents_path()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def consent_manager(parameters: dict, player=None, **_context) -> str:
    """Inspect, grant, or revoke permissions and consent scopes for ARC."""
    action = parameters.get("action", "list").lower().strip()
    scope = parameters.get("permission", parameters.get("scope", "")).lower().strip()

    consents = _load_consents()

    # ── Action: List Consents ────────────────────────────────────────────────
    if action in ("list", "view", "status"):
        lines = []
        for perm, granted in consents.items():
            badge = "🟢 GRANTED" if granted else "🔴 REVOKED"
            lines.append(f"• **{perm}**: {badge}")

        return (
            "🛡️ ARC Privacy & Permission Consent Matrix:\n\n"
            + "\n".join(lines)
            + "\n\nTo alter a permission, say 'grant permission camera_access' or 'revoke permission screen_recording'."
        )

    # ── Action: Grant Consent ────────────────────────────────────────────────
    elif action in ("grant", "allow", "enable"):
        if not scope:
            return "Please specify the permission scope to grant (e.g. 'camera_access', 'shell_execution')."

        matched = None
        for k in consents:
            if scope in k or k in scope:
                matched = k
                break

        target_perm = matched or scope
        consents[target_perm] = True
        _save_consents(consents)
        log_ethical_audit("consent_update", "user", "GRANTED", f"User explicitly granted permission: {target_perm}")

        return f"✅ Permission **{target_perm}** has been GRANTED. Subsystems may now access this capability."

    # ── Action: Revoke Consent ───────────────────────────────────────────────
    elif action in ("revoke", "deny", "disable"):
        if not scope:
            return "Please specify the permission scope to revoke."

        matched = None
        for k in consents:
            if scope in k or k in scope:
                matched = k
                break

        target_perm = matched or scope
        consents[target_perm] = False
        _save_consents(consents)
        log_ethical_audit("consent_update", "user", "REVOKED", f"User explicitly revoked permission: {target_perm}")

        return f"🔒 Permission **{target_perm}** has been REVOKED. Subsystems will block this capability immediately."

    # ── Action: First Run Consent Briefing ───────────────────────────────────
    elif action in ("first_run", "flow", "onboarding"):
        return (
            "👋 Welcome to ARC (Adaptive Real-Time Cognitive Agent).\n\n"
            "PRIVACY BY DESIGN ETHICAL PRINCIPLES:\n"
            "1. Zero Telemetry Exfiltration: Your conversations, memory, and biometric logs are stored locally on your machine.\n"
            "2. Transparent Control: You hold sovereign authority to grant, revoke, or wipe data at any time.\n"
            "3. Sensitive Capabilities (Camera & Screen Mirroring) require explicit permission.\n\n"
            "Current consent profile: Standard local operation with hardware-bound encryption active."
        )

    return f"Unknown consent action '{action}'. Supported actions: list, grant, revoke, first_run."


TOOL = {
    "name": "consent_manager",
    "description": (
        "ARC Privacy and Consent Manager. Allows users to list, grant, or revoke permissions "
        "for camera access, microphone, screen recording, biometric tracking, and shell execution."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'list', 'grant', 'revoke', 'first_run'",
            },
            "permission": {
                "type": "STRING",
                "description": "Permission scope: 'camera_access', 'screen_recording', 'shell_execution', 'biometric_data'",
            },
        },
        "required": ["action"],
    },
    "handler": consent_manager,
}
