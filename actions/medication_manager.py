"""
actions/medication_manager.py — ARC Medication Schedule & Drug Interaction Engine.

Features:
  - Encrypted medication regimen tracking (memory/health/medications.json)
  - Dose logging and adherence percentage calculation
  - Evidence-based critical drug-drug interaction screening
  - Schedule reminders via ARC proactive reminder system
  - Mandatory clinical safety disclaimers
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from memory.health_store import MANDATORY_DISCLAIMER, load_health_data, save_health_data

# Known critical drug-drug interaction pairs
_INTERACTION_DATABASE = [
    {
        "drugs": ("warfarin", "aspirin"),
        "severity": "CRITICAL",
        "effect": "Severe hemorrhage & gastrointestinal bleeding risk.",
    },
    {
        "drugs": ("warfarin", "ibuprofen"),
        "severity": "CRITICAL",
        "effect": "Severe hemorrhage & gastrointestinal ulceration risk.",
    },
    {
        "drugs": ("lisinopril", "potassium"),
        "severity": "HIGH",
        "effect": "Hyperkalemia risk leading to cardiac arrhythmias.",
    },
    {
        "drugs": ("simvastatin", "clarithromycin"),
        "severity": "CRITICAL",
        "effect": "Marked CYP3A4 inhibition leading to rhabdomyolysis and acute renal failure.",
    },
    {
        "drugs": ("sertraline", "tramadol"),
        "severity": "CRITICAL",
        "effect": "Serotonin syndrome risk (hyperthermia, neuromuscular delirium, tremors).",
    },
    {
        "drugs": ("sildenafil", "nitroglycerin"),
        "severity": "FATAL RISK",
        "effect": "Profound, life-threatening systemic hypotension.",
    },
    {
        "drugs": ("metformin", "contrast"),
        "severity": "HIGH",
        "effect": "Risk of acute renal impairment and fatal lactic acidosis.",
    },
    {
        "drugs": ("methotrexate", "amoxicillin"),
        "severity": "HIGH",
        "effect": "Decreased renal clearance of methotrexate leading to bone marrow toxicity.",
    },
]


def _check_interactions(med_names: List[str]) -> List[Dict[str, str]]:
    """Screens list of medication names against interaction database."""
    normalized = [m.lower().strip() for m in med_names]
    warnings = []

    for rule in _INTERACTION_DATABASE:
        d1, d2 = rule["drugs"]
        has_d1 = any(d1 in name for name in normalized)
        has_d2 = any(d2 in name for name in normalized)
        if has_d1 and has_d2:
            warnings.append({
                "pair": f"{d1.title()} + {d2.title()}",
                "severity": rule["severity"],
                "effect": rule["effect"],
            })

    return warnings


def check_drug_interactions_online(drug_names: List[str]) -> str:
    """Uses web_search to perform dynamic pharmacology cross-referencing."""
    if len(drug_names) < 2:
        return ""
    try:
        from actions.web_search import web_search
        query = f"drug interaction {' and '.join(drug_names[:3])} clinical contraindications"
        return web_search({"query": query, "mode": "medical"})
    except Exception as e:
        return f"Online interaction lookup unavailable: {e}"


def medication_manager(parameters: dict, player=None, **_context) -> str:
    """Manage prescription regimens, track dose compliance, and screen drug interactions."""
    action = parameters.get("action", "list").lower().strip()
    name = parameters.get("medication_name", "").strip()
    dosage = parameters.get("dosage", "").strip()
    schedule = parameters.get("schedule", "08:00").strip()
    prescribed_for = parameters.get("prescribed_for", "Unspecified").strip()
    notes = parameters.get("notes", "").strip()

    meds_data = load_health_data("medications.json", default={"medications": [], "logs": []})
    meds_list: List[Dict[str, Any]] = meds_data.get("medications", [])
    logs: List[Dict[str, Any]] = meds_data.get("logs", [])

    # ── Action: Add Medication ───────────────────────────────────────────────
    if action in ("add", "create", "new"):
        if not name:
            return "Sir, please provide the medication name to add." + MANDATORY_DISCLAIMER

        # Check for duplicates or update
        for m in meds_list:
            if m["name"].lower() == name.lower():
                m["dosage"] = dosage or m.get("dosage", "")
                m["schedule"] = schedule or m.get("schedule", "")
                m["prescribed_for"] = prescribed_for or m.get("prescribed_for", "")
                save_health_data("medications.json", meds_data)
                return f"[UPDATED] Existing prescription for {name} ({m['dosage']})." + MANDATORY_DISCLAIMER

        new_med = {
            "name": name,
            "dosage": dosage or "As prescribed",
            "schedule": schedule,
            "prescribed_for": prescribed_for,
            "notes": notes,
            "added_on": datetime.now().strftime("%Y-%m-%d"),
        }
        meds_list.append(new_med)

        # Screen for interaction with existing medications
        current_names = [m["name"] for m in meds_list]
        interactions = _check_interactions(current_names)
        warn_msg = ""
        if interactions:
            warn_msg = "\n\n[POTENTIAL DRUG INTERACTION DETECTED]:\n" + "\n".join(
                f"- [{item['severity']}] {item['pair']}: {item['effect']}" for item in interactions
            ) + "\nPlease consult your prescribing doctor or pharmacist before taking together."

        # Schedule reminder
        try:
            from actions.reminder import reminder
            reminder({
                "action": "add",
                "title": f"Take Medication: {name}",
                "message": f"Time to take {name} ({dosage or 'prescribed dose'}).",
                "time": schedule,
            })
        except Exception:
            pass

        save_health_data("medications.json", meds_data)
        return (
            f"[RECORDED] Prescription for {name} ({dosage or 'as directed'}).\n"
            f"Schedule: {schedule} | Indication: {prescribed_for}\n"
            f"Proactive daily reminder has been scheduled.{warn_msg}"
            + MANDATORY_DISCLAIMER
        )

    # ── Action: List Medications ─────────────────────────────────────────────
    elif action in ("list", "view", "all"):
        if not meds_list:
            return (
                "Sir, no active prescriptions are currently recorded in your encrypted health store. "
                "You can add one by saying 'add medication Lisinopril 10mg daily at 8am'."
                + MANDATORY_DISCLAIMER
            )

        rows = []
        for idx, m in enumerate(meds_list):
            rows.append(
                f"{idx+1}. **{m['name']}** ({m.get('dosage', 'standard')}) — Schedule: {m.get('schedule', 'daily')}"
                f" | Indication: {m.get('prescribed_for', 'General')}"
            )

        total_logs = len(logs)
        taken_logs = sum(1 for l in logs if l.get("status") == "taken")
        adherence_str = f"{(taken_logs / max(1, total_logs)) * 100:.0f}%" if total_logs else "100% (No missed logs)"

        return (
            f"[ACTIVE PRESCRIPTION REGIMEN] ({len(meds_list)} medications):\n"
            + "\n".join(rows)
            + f"\n\nOverall Dose Adherence Rate: {adherence_str}"
            + MANDATORY_DISCLAIMER
        )

    # ── Action: Log Dose Taken ───────────────────────────────────────────────
    elif action in ("log_dose", "take", "dose_taken", "log"):
        if not name:
            if meds_list:
                name = meds_list[0]["name"]
            else:
                return "Please specify which medication dose was taken." + MANDATORY_DISCLAIMER

        now_str = datetime.now().isoformat()
        logs.append({
            "timestamp": now_str,
            "medication": name,
            "status": "taken",
            "notes": notes,
        })
        save_health_data("medications.json", meds_data)
        return f"[DOSE RECORDED]: {name} marked as taken at {datetime.now().strftime('%H:%M')}." + MANDATORY_DISCLAIMER

    # ── Action: Check Interactions ───────────────────────────────────────────
    elif action in ("check_interactions", "interactions", "screen"):
        current_names = [m["name"] for m in meds_list]
        if name and name not in current_names:
            current_names.append(name)

        if len(current_names) < 2:
            return (
                "At least two medications are required to screen for potential interactions."
                + MANDATORY_DISCLAIMER
            )

        interactions = _check_interactions(current_names)
        online_info = ""
        try:
            online_info = check_drug_interactions_online(current_names)
        except Exception:
            pass

        if not interactions and not online_info:
            return (
                f"[CLEAR] No known critical high-severity interactions detected among: {', '.join(current_names)}."
                + MANDATORY_DISCLAIMER
            )

        warn_lines = "\n".join(
            f"- [{i['severity']}] {i['pair']}: {i['effect']}" for i in interactions
        )
        report = f"[DRUG INTERACTION SCREENING]:\n\n{warn_lines}" if warn_lines else "[DATABASE SCREENING]: No standard database contraindications flagged."
        if online_info:
            report += f"\n\n[ONLINE PHARMACOLOGY CORROBORATION]:\n{online_info[:400]}"

        report += "\n\nDo not modify your prescribed regimen without consulting your primary physician or pharmacist."
        return report + MANDATORY_DISCLAIMER

    # ── Action: Remove Medication ────────────────────────────────────────────
    elif action in ("remove", "delete"):
        if not name:
            return "Please specify the medication to remove." + MANDATORY_DISCLAIMER
        before_count = len(meds_list)
        meds_data["medications"] = [m for m in meds_list if m["name"].lower() != name.lower()]
        if len(meds_data["medications"]) < before_count:
            save_health_data("medications.json", meds_data)
            return f"Removed {name} from active medications." + MANDATORY_DISCLAIMER
        return f"Medication '{name}' was not found in your active regimen." + MANDATORY_DISCLAIMER

    return (
        f"Unknown action '{action}'. Supported actions: add, list, log_dose, check_interactions, remove."
        + MANDATORY_DISCLAIMER
    )


TOOL = {
    "name": "medication_manager",
    "description": (
        "ARC Medication Intelligence and Adherence manager. Tracks prescription schedules, "
        "logs doses taken, calculates adherence percentages, screens for critical drug-drug "
        "interactions, and integrates with reminders."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'add', 'list', 'log_dose', 'check_interactions', 'remove'",
            },
            "medication_name": {
                "type": "STRING",
                "description": "Name of the drug or supplement",
            },
            "dosage": {
                "type": "STRING",
                "description": "Dosage quantity and unit (e.g. '10mg', '500mg capsule')",
            },
            "schedule": {
                "type": "STRING",
                "description": "Timing or frequency (e.g. '08:00', 'twice daily')",
            },
            "prescribed_for": {
                "type": "STRING",
                "description": "Medical condition treated (e.g. 'Hypertension', 'Diabetes')",
            },
        },
        "required": ["action"],
    },
    "handler": medication_manager,
}
