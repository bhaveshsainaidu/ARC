"""
memory/health_store.py — Encrypted Health Data Storage & Clinical Guardrails for ARC.

Ensures HIPAA-aligned cryptographic security at rest for all personal health data:
  - Hardware-bound Fernet AES-128-CBC + HMAC-SHA256 encryption
  - Mandatory disclaimer constants
  - Emergency red flag definitions
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from threading import Lock
from typing import Any

from memory.config_manager import _get_fernet

_health_lock = Lock()

MANDATORY_DISCLAIMER = (
    "\n\n[MEDICAL DISCLAIMER]: ARC is an AI cognitive assistant, not a licensed medical professional. "
    "This analysis is for informational purposes only and does not constitute medical advice, clinical determination, "
    "or treatment recommendations. Always consult a qualified physician or healthcare provider for personal "
    "health concerns, prescriptions, or medical emergencies. In an emergency, contact your local emergency "
    "services (e.g. 911 / 112) immediately."
)

EMERGENCY_RED_FLAGS = [
    ("chest pain", "radiating pain to left arm, neck, or jaw (possible myocardial infarction)"),
    ("shortness of breath", "severe sudden respiratory distress or cyanosis"),
    ("facial drooping", "unilateral facial droop, arm weakness, or speech slurring (FAST stroke signs)"),
    ("loss of consciousness", "syncope, unresponsiveness, or prolonged confusion"),
    ("severe hemorrhage", "uncontrolled arterial bleeding or vomiting blood"),
    ("severe allergic reaction", "throat swelling, anaphylaxis, stridor, or hives with dyspnea"),
    ("worst headache of life", "sudden thunderclap headache (possible subarachnoid hemorrhage)"),
    ("suicidal ideation", "immediate self-harm risk (Crisis Lifeline: Call/Text 988)"),
]


def _get_health_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    h_dir = base / "memory" / "health"
    h_dir.mkdir(parents=True, exist_ok=True)
    return h_dir


def load_health_data(filename: str, default: Any = None) -> Any:
    """Decrypts and loads JSON health data from disk."""
    with _health_lock:
        filepath = _get_health_dir() / filename
        if not filepath.exists():
            return default if default is not None else {}
        try:
            raw = filepath.read_bytes()
            if not raw:
                return default if default is not None else {}
            fernet = _get_fernet()
            decrypted = fernet.decrypt(raw)
            return json.loads(decrypted.decode("utf-8"))
        except Exception:
            # Fallback in case file was unencrypted or corrupted
            try:
                text = filepath.read_text(encoding="utf-8")
                return json.loads(text)
            except Exception:
                return default if default is not None else {}


def save_health_data(filename: str, data: Any) -> None:
    """Encrypts and persists JSON health data to disk with Fernet."""
    with _health_lock:
        filepath = _get_health_dir() / filename
        fernet = _get_fernet()
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        encrypted = fernet.encrypt(payload)
        filepath.write_bytes(encrypted)
