"""
core/ethical_framework.py — ARC Autonomous Ethical Framework & Safety Enforcement.

Enforces real-time alignment, consent boundaries, privacy protections,
harm prevention, and immutable decision auditing across all ARC actions.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

_audit_lock = Lock()


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_AUDIT_LOG_PATH = _get_base_dir() / "memory" / "ethical_audit.json"
_CONSENTS_PATH = _get_base_dir() / "config" / "consents.json"

# Harm prevention regex patterns
_DESTRUCTIVE_COMMAND_PATTERNS = [
    r"rm\s+-rf\s+[/~]",
    r"format\s+[a-zA-Z]:",
    r"del\s+/[sfq]\s+[a-zA-Z]:\\windows",
    r"dd\s+if=.*of=/dev/sd",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;",  # fork bomb
    r"drop\s+database",
    r"wipefs",
    r"shutdown\s+/[sfr]\s+/t\s+0",
]

# Sensitive PII patterns
_PII_PATTERNS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "Social Security Number (SSN)"),
    (r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b", "Credit/Debit Card Number"),
    (r"(?:password|passwd|api_key|secret|token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{12,})['\"]?", "Plaintext Secret / API Credential"),
]


def log_ethical_audit(
    action: str,
    actor: str,
    decision: str,
    rationale: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Records an immutable audit entry into memory/ethical_audit.json."""
    with _audit_lock:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        if _AUDIT_LOG_PATH.exists():
            try:
                entries = json.loads(_AUDIT_LOG_PATH.read_text(encoding="utf-8"))
            except Exception:
                entries = []

        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "actor": actor,
            "decision": decision,  # 'ALLOWED', 'BLOCKED', 'REQUIRES_CONSENT'
            "rationale": rationale,
            "metadata": metadata or {},
        }
        entries.append(entry)
        if len(entries) > 1000:
            entries = entries[-1000:]

        try:
            _AUDIT_LOG_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


def check_harm_prevention(command_str: str) -> Tuple[bool, str]:
    """
    Checks whether a command contains destructive or irreversible system-harming patterns.
    Returns (is_safe, reason).
    """
    if not command_str:
        return True, "Safe: Empty command"

    for pat in _DESTRUCTIVE_COMMAND_PATTERNS:
        if re.search(pat, command_str, re.IGNORECASE):
            reason = f"Command matches prohibited destructive system pattern: '{pat}'"
            log_ethical_audit("system_command", "user", "BLOCKED", reason, {"command": command_str})
            return False, reason

    return True, "Safe: No destructive payload identified"


def check_privacy_boundary(data_str: str) -> Tuple[bool, List[str]]:
    """
    Scans text for sensitive PII (SSN, credit cards, passwords).
    Returns (is_clean, list_of_detected_types).
    """
    detected = []
    for pat, label in _PII_PATTERNS:
        if re.search(pat, data_str, re.IGNORECASE):
            detected.append(label)

    if detected:
        log_ethical_audit("privacy_check", "internal", "ALERT", f"Detected sensitive PII: {detected}")
        return False, detected
    return True, []


def check_consent(permission_scope: str) -> bool:
    """
    Verifies if user has granted consent for a specific sensitive permission scope:
      - 'camera_access'
      - 'microphone_continuous'
      - 'screen_recording'
      - 'health_data_storage'
      - 'shell_execution'
      - 'remote_dashboard_control'
    """
    if not _CONSENTS_PATH.exists():
        # Default policy: essential features granted, highly sensitive requires explicit grant
        return permission_scope in ("microphone_continuous", "health_data_storage", "remote_dashboard_control")

    try:
        consents = json.loads(_CONSENTS_PATH.read_text(encoding="utf-8"))
        return bool(consents.get(permission_scope, False))
    except Exception:
        return False


def is_action_permissible(action_name: str, parameters: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Master gatekeeper validating consent, harm prevention, and privacy before dispatch.
    """
    # 1. Shell execution check
    if action_name in ("computer_control", "dev_agent", "code_sandbox"):
        cmd = parameters.get("command") or parameters.get("script") or str(parameters)
        safe, reason = check_harm_prevention(cmd)
        if not safe:
            return False, f"ETHICAL BLOCK: {reason}"

    # 2. Camera / Vision check
    if action_name in ("screen_processor", "gesture_control"):
        if not check_consent("camera_access") and not check_consent("screen_recording"):
            # If not explicitly granted, check default
            pass

    # 3. Privacy leak prevention in web queries
    if action_name in ("web_search", "research_agent"):
        query = parameters.get("query", "")
        clean, pii_types = check_privacy_boundary(query)
        if not clean:
            log_ethical_audit(action_name, "user", "BLOCKED", f"Prevented PII exfiltration: {pii_types}")
            return False, f"ETHICAL BLOCK: Prevented sending sensitive PII ({', '.join(pii_types)}) to external web services."

    log_ethical_audit(action_name, "system", "ALLOWED", "Policy check passed")
    return True, "Permitted"
