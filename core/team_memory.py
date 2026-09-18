"""
core/team_memory.py — ARC Team Identity, Personality Core & Face Reference Store.

Maintains persistent memory of:
  - Bhavesh (Team Lead / Founder, male)
  - Teammate 1 (female)
  - Teammate 2 (female)
  - Roles, personality traits, and photo references in memory/faces/
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_TEAM_FILE = _get_base_dir() / "memory" / "team_profiles.json"
_FACES_DIR = _get_base_dir() / "memory" / "faces"


_DEFAULT_TEAM = {
    "team_name": "ARC Core Engineering Team",
    "members": {
        "bhavesh": {
            "name": "Bhavesh",
            "role": "Founder & Lead Architect",
            "gender": "male",
            "personality": "Visionary, technical lead, fast-paced builder, relentless problem-solver driving autonomous AI innovation.",
            "photo": "memory/faces/bhavesh.jpg",
        },
        "teammate_1": {
            "name": "Teammate 1",
            "role": "Core Member & Researcher",
            "gender": "female",
            "personality": "Analytical, collaborative, creative thinker focusing on design and evaluation.",
            "photo": "memory/faces/teammate1.jpg",
        },
        "teammate_2": {
            "name": "Teammate 2",
            "role": "Core Member & Specialist",
            "gender": "female",
            "personality": "Strategic, execution-driven, detail-oriented builder.",
            "photo": "memory/faces/teammate2.jpg",
        },
    },
}


def ensure_team_memory() -> Dict[str, Any]:
    """Ensures team memory file and faces directory exist."""
    _FACES_DIR.mkdir(parents=True, exist_ok=True)
    if not _TEAM_FILE.exists():
        _TEAM_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TEAM_FILE.write_text(json.dumps(_DEFAULT_TEAM, indent=2), encoding="utf-8")
        return dict(_DEFAULT_TEAM)
    try:
        return json.loads(_TEAM_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULT_TEAM)


def update_team_member(
    key_or_name: str,
    name: Optional[str] = None,
    role: Optional[str] = None,
    personality: Optional[str] = None,
    gender: Optional[str] = None,
    photo_path: Optional[str] = None,
) -> tuple[bool, str]:
    """Updates or adds a team member profile."""
    data = ensure_team_memory()
    members = data.setdefault("members", {})

    target_key = key_or_name.lower().replace(" ", "_")

    # Match existing key or name
    matched_k = None
    for k, v in members.items():
        if k == target_key or (v.get("name") and v["name"].lower() == key_or_name.lower()):
            matched_k = k
            break

    if not matched_k:
        matched_k = target_key
        members[matched_k] = {}

    m = members[matched_k]
    if name:
        m["name"] = name
    if role:
        m["role"] = role
    if personality:
        m["personality"] = personality
    if gender:
        m["gender"] = gender
    if photo_path:
        m["photo"] = photo_path

    _TEAM_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return True, f"Updated profile for {m.get('name', matched_k)}."


def get_team_context_str() -> str:
    """Formats team identities and personalities for injection into ARC system prompt."""
    data = ensure_team_memory()
    members = data.get("members", {})
    if not members:
        return ""

    lines = [
        "👥 [KNOWN TEAM & USER RECOGNITION CONTEXT]",
        "You belong to and directly assist this 3-member team (Bhavesh and his 2 female teammates):",
    ]
    for k, v in members.items():
        name = v.get("name", k)
        role = v.get("role", "Team Member")
        gen = v.get("gender", "unspecified")
        pers = v.get("personality", "")
        lines.append(f"• {name} ({gen.capitalize()} - {role}): {pers}")

    lines.append(
        "When any member is in front of the camera or speaking, recognize and address them with familiarity, respect, and loyalty."
    )
    return "\n".join(lines)
