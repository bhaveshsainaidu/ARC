"""
actions/team_intelligence.py — ARC Team Recognition, Profiles & Face Verification.

Manages team profiles (Bhavesh + 2 teammates), personality traits,
and camera recognition matching.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.team_memory import ensure_team_memory, update_team_member


def team_intelligence(parameters: dict, player=None, **_context) -> str:
    """Manage team member profiles, roles, personalities, and face references."""
    action = parameters.get("action", "view").lower().strip()
    name = parameters.get("name", "").strip()
    role = parameters.get("role", "").strip()
    personality = parameters.get("personality", "").strip()
    gender = parameters.get("gender", "").strip()
    photo_path = parameters.get("photo_path", "").strip()

    data = ensure_team_memory()
    members = data.get("members", {})

    # ── Action: View Team Profiles ───────────────────────────────────────────
    if action in ("view", "list", "list_team", "members", "get_profile"):
        if name or action == "get_profile":
            lookup_name = (name or parameters.get("member_key", "")).lower()
            for k, m in members.items():
                if lookup_name in m.get("name", "").lower() or lookup_name in k.lower():
                    photo_status = "🖼️ Photo on file" if m.get("photo") and Path(m["photo"]).exists() else "No photo yet"
                    return (
                        f"👤 ARC Team Profile: **{m.get('name', k)}**\n"
                        f"• Role: {m.get('role', 'Core Member')}\n"
                        f"• Gender: {m.get('gender', 'unspecified').capitalize()}\n"
                        f"• Personality Traits: {m.get('personality', 'Not specified')}\n"
                        f"• Photo Reference: {photo_status}"
                    )
        lines = []
        for k, m in members.items():
            photo_status = "🖼️ Photo on file" if m.get("photo") and Path(m["photo"]).exists() else "No photo yet"
            lines.append(
                f"• **{m.get('name', k)}** ({m.get('gender', 'unspecified').capitalize()} - {m.get('role', 'Member')})\n"
                f"  Personality: {m.get('personality', 'Not specified')}\n"
                f"  Reference: {photo_status}"
            )
        return (
            "👥 ARC Team Profile Roster:\n\n"
            + "\n\n".join(lines)
            + "\n\nTo update or set teammate details, say: 'update teammate 1 name Sarah role Frontend Lead personality creative and fast'."
        )

    # ── Action: Update or Register Member ────────────────────────────────────
    elif action in ("update", "register", "set", "add"):
        if not name and not parameters.get("member_key"):
            return "Sir, please provide the name or key of the team member to update (e.g. 'Bhavesh', 'teammate_1', or 'teammate_2')."

        target = parameters.get("member_key") or name
        ok, msg = update_team_member(
            target,
            name=name if name else None,
            role=role if role else None,
            personality=personality if personality else None,
            gender=gender if gender else None,
            photo_path=photo_path if photo_path else None,
        )
        return f"✅ {msg}\nARC now remembers this profile and will incorporate it into voice, camera, and collaboration interactions."

    # ── Action: Who is in front of camera / Identify ─────────────────────────
    elif action in ("identify", "who_is_this", "recognize"):
        # Returns current context of team
        names_str = ", ".join(m.get("name", k) for k, m in members.items())
        return (
            f"🔍 Person Recognition Mode Active.\n"
            f"Known Team Members: {names_str}.\n"
            f"To verify visually via camera, please activate camera vision: 'ARC, what do you see in the camera?'"
        )

    return f"Unknown team action '{action}'. Supported actions: view, update, register."


TOOL = {
    "name": "team_intelligence",
    "description": (
        "ARC Team Identity & Recognition Manager. Stores and recalls profiles, personalities, "
        "and roles for Bhavesh and his teammates, enabling personalized visual and conversational interaction."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'view', 'update', 'register'",
            },
            "name": {
                "type": "STRING",
                "description": "Name of the team member (e.g. 'Bhavesh', 'Alice', 'Chloe')",
            },
            "member_key": {
                "type": "STRING",
                "description": "Optional slot key: 'bhavesh', 'teammate_1', 'teammate_2'",
            },
            "role": {
                "type": "STRING",
                "description": "Role in the project (e.g. 'Founder', 'AI Specialist', 'Designer')",
            },
            "personality": {
                "type": "STRING",
                "description": "Personality traits and collaboration preferences",
            },
            "gender": {
                "type": "STRING",
                "description": "'male' or 'female'",
            },
            "photo_path": {
                "type": "STRING",
                "description": "Path to reference face photo",
            },
        },
        "required": [],
    },
    "handler": team_intelligence,
}
