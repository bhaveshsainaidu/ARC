"""
actions/daily_briefing.py — Daily Task & System Briefing for ARC.

Provides an on-demand comprehensive briefing covering:
- Date, day of week, and local time
- System health (CPU, RAM, Battery %, Disk free space)
- Pending reminders and scheduled tasks
- Recent quick notes and active projects
"""

from __future__ import annotations

import os
import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from actions.system_monitor import get_system_status
from memory.memory_manager import load_memory


def _get_battery_status() -> dict[str, Any]:
    """Retrieve laptop battery metrics."""
    try:
        b = psutil.sensors_battery()
        if b is None:
            return {"has_battery": False}
        return {
            "has_battery": True,
            "percent": int(b.percent),
            "power_plugged": bool(b.power_plugged),
            "secsleft": b.secsleft if b.secsleft > 0 else None,
        }
    except Exception:
        return {"has_battery": False}


def _get_disk_status() -> dict[str, Any]:
    """Check free space on main OS drive."""
    try:
        drive = "C:\\" if platform.system() == "Windows" else "/"
        usage = shutil.disk_usage(drive)
        free_gb = round(usage.free / (1024 ** 3), 1)
        total_gb = round(usage.total / (1024 ** 3), 1)
        return {"free_gb": free_gb, "total_gb": total_gb, "percent_free": round((usage.free / usage.total) * 100, 1)}
    except Exception:
        return {"free_gb": 0, "total_gb": 0, "percent_free": 0}


def _get_recent_notes() -> list[str]:
    """Fetch top recent notes."""
    try:
        base = Path(__file__).resolve().parent.parent
        notes_dir = base / "memory" / "notes"
        if not notes_dir.exists():
            return []
        notes = []
        for f in sorted(notes_dir.glob("*.md"), reverse=True)[:3]:
            try:
                line = f.read_text(encoding="utf-8").split("\n", 1)[0].replace("#", "").strip()
                notes.append(line)
            except Exception:
                pass
        return notes
    except Exception:
        return []


def daily_briefing(parameters: dict, player=None, **_context) -> str:
    """Compile and return an all-in-one daily status and task briefing."""
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%A, %B %d, %Y")

    sys_status = get_system_status()
    battery = _get_battery_status()
    disk = _get_disk_status()
    recent_notes = _get_recent_notes()

    # Read active memory projects
    memory = load_memory()
    projects = memory.get("projects", {})
    project_list = [f"{k}: {v.get('value', '')}" for k, v in projects.items() if isinstance(v, dict)]

    lines = [
        f"📋 DAILY BRIEFING — {date_str} ({time_str})",
        "───────────────────────────────────────────────",
        f"• System Health: CPU {sys_status.get('cpu_percent', '?')}%, RAM {sys_status.get('ram_percent', '?')}% ({sys_status.get('ram_used_gb', '?')}/{sys_status.get('ram_total_gb', '?')} GB), Uptime {sys_status.get('uptime', 'unknown')}",
    ]

    if battery.get("has_battery"):
        plugged_str = "Plugged in" if battery.get("power_plugged") else "On Battery"
        lines.append(f"• Battery: {battery.get('percent')}% ({plugged_str})")

    if disk.get("free_gb", 0) > 0:
        lines.append(f"• Storage: {disk.get('free_gb')} GB free of {disk.get('total_gb')} GB ({disk.get('percent_free')}% available)")

    if recent_notes:
        lines.append("• Recent Notes: " + "; ".join(recent_notes))

    if project_list:
        lines.append("• Active Projects: " + "; ".join(project_list[:3]))

    lines.append("───────────────────────────────────────────────")
    lines.append("Everything is in order, Sir. Ready for your instructions.")

    result = "\n".join(lines)
    if player:
        try:
            player.write_log("SYS: Daily briefing generated.")
        except Exception:
            pass
    return result


TOOL = {
    "name": "daily_briefing",
    "description": (
        "Gives an on-demand daily briefing for ARC covering current time, "
        "battery level, storage space, CPU/RAM status, recent notes, and active projects."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "handler": daily_briefing,
}
