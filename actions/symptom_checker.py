"""
actions/symptom_checker.py — ARC Clinical Symptom Triage & Risk Assessment.

Features:
  - Immediate red flag emergency detection (FAST stroke signs, cardiac arrest, severe respiratory failure)
  - Structured 4-tier triage (Emergency, Urgent Care, Routine Outpatient, Home Self-Care)
  - Differential topics to discuss with a physician
  - Encrypted history storage in memory/health/symptom_history.json
  - Mandatory clinical safety disclaimers
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from memory.health_store import (
    EMERGENCY_RED_FLAGS,
    MANDATORY_DISCLAIMER,
    load_health_data,
    save_health_data,
)


def _evaluate_red_flags(symptoms_text: str) -> List[tuple[str, str]]:
    """Checks input against critical emergency red flag symptom dictionary."""
    found = []
    text_lower = symptoms_text.lower()
    for flag_term, desc in EMERGENCY_RED_FLAGS:
        if flag_term in text_lower:
            found.append((flag_term, desc))
    return found


def _determine_triage_tier(severity: int, duration_days: float, red_flags: list) -> str:
    if red_flags or severity >= 9:
        return "EMERGENCY (IMMEDIATE ER / 911)"
    if severity >= 6 or duration_days > 14:
        return "URGENT CARE (Within 24 Hours)"
    if severity >= 4 or duration_days > 5:
        return "ROUTINE OUTPATIENT CLINIC (1-3 Days)"
    return "SUPPORTIVE HOME CARE & MONITORING"


def symptom_checker(parameters: dict, player=None, **_context) -> str:
    """Assess user reported symptoms and determine triage level with clinical safety rails."""
    symptoms = parameters.get("symptoms", "").strip()
    duration = parameters.get("duration", "1 day").strip()
    severity = int(parameters.get("severity", 4))
    severity = max(1, min(10, severity))
    age = parameters.get("patient_age", "Adult")

    if not symptoms:
        return (
            "Sir, please describe the symptoms you are experiencing, including how long they have "
            "been present and their severity on a scale of 1 to 10." + MANDATORY_DISCLAIMER
        )

    # 1. Red Flag Screening
    red_flags = _evaluate_red_flags(symptoms)
    if red_flags:
        flag_details = "\n".join(f"  * {name.upper()}: {desc}" for name, desc in red_flags)
        emergency_response = (
            f"[CRITICAL RED FLAG WARNING DETECTED]:\n\n"
            f"{flag_details}\n\n"
            f"[IMMEDIATE ACTION REQUIRED]:\n"
            f"Do not drive yourself. Call 911 (or your local emergency services) immediately or have someone "
            f"transport you to the nearest emergency room without delay."
            f"{MANDATORY_DISCLAIMER}"
        )
        return emergency_response

    # Parse duration in days
    dur_days = 1.0
    num_match = re.search(r"(\d+)", duration)
    if num_match:
        val = float(num_match.group(1))
        if "week" in duration.lower():
            dur_days = val * 7
        elif "month" in duration.lower():
            dur_days = val * 30
        else:
            dur_days = val

    tier = _determine_triage_tier(severity, dur_days, red_flags)

    # Persist encrypted record
    try:
        history = load_health_data("symptom_history.json", default=[])
        history.append({
            "timestamp": datetime.now().isoformat(),
            "symptoms": symptoms,
            "duration": duration,
            "severity": severity,
            "tier": tier,
        })
        save_health_data("symptom_history.json", history[-100:])
    except Exception:
        pass

    # Supportive advice and questions for doctor
    recs = [
        "Hydration & Rest: Maintain fluid intake and monitor for fever or progression.",
        "Track Symptom Progression: Record temperature readings and any new focal symptoms.",
        "When to Escalate: Seek emergency care immediately if you develop shortness of breath, severe pain, or confusion.",
    ]
    doctor_questions = [
        f"What clinical evaluations are recommended for persistent {symptoms}?",
        "Are there any prescription or OTC interactions with my current routine?",
        "What specific warning signs should prompt an emergency room visit?",
    ]

    recs_str = "\n".join(f"- {r}" for r in recs)
    questions_str = "\n".join(f"- \"{q}\"" for q in doctor_questions)

    return (
        f"[ARC Clinical Triage Assessment]:\n\n"
        f"Reported Symptoms: {symptoms}\n"
        f"Duration: {duration} | Severity: {severity}/10 | Patient Group: {age}\n"
        f"Recommended Care Level: **{tier}**\n\n"
        f"Guidance & Monitoring:\n{recs_str}\n\n"
        f"Questions to Discuss with Your Doctor:\n{questions_str}"
        f"{MANDATORY_DISCLAIMER}"
    )


TOOL = {
    "name": "symptom_checker",
    "description": (
        "ARC Healthcare Symptom Triage agent. Screens for critical red flag emergencies, "
        "provides 4-tier care triage recommendations, suggests doctor discussion topics, "
        "and securely records encrypted symptom history."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "symptoms": {
                "type": "STRING",
                "description": "Description of physical symptoms or complaints",
            },
            "duration": {
                "type": "STRING",
                "description": "How long symptoms have lasted (e.g. '2 days', '3 weeks')",
            },
            "severity": {
                "type": "INTEGER",
                "description": "Subjective pain or distress score from 1 (mild) to 10 (unbearable)",
            },
            "patient_age": {
                "type": "STRING",
                "description": "Approximate age or category (e.g. '30', 'Child', 'Senior')",
            },
        },
        "required": ["symptoms"],
    },
    "handler": symptom_checker,
}
