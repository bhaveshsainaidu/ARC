"""
core/greeting.py — Startup greeting prompt generation for ARC.

Constructs a local-only startup greeting prompt based on local time,
system status, identity settings, and previous session context.
Never fetches external news or triggers network actions on startup.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def format_health_summary(system: dict[str, Any]) -> str:
    """Format a compact system health summary string."""
    cpu = system.get("cpu_percent", "?")
    ram_pct = system.get("ram_percent", "?")
    ram_used = system.get("ram_used_gb", "?")
    ram_total = system.get("ram_total_gb", "?")
    uptime = system.get("uptime", "unknown")

    health = f"CPU {cpu}%, memory {ram_pct}% ({ram_used} of {ram_total} GB), uptime {uptime}"
    if system.get("gpu_percent") is not None:
        health += f", GPU {system['gpu_percent']}%"
    return health


def build_startup_greeting_prompt(
    time_str: Optional[str] = None,
    system_status: Optional[dict[str, Any]] = None,
    lang: str = "",
    name: str = "",
    last_session: Optional[dict[str, Any]] = None,
    pending_tasks: Optional[list[dict]] = None,
) -> str:
    """
    Build the [STARTUP_GREETING] directive for the Live session.
    Guaranteed to be local-only: does not browse, fetch news, or call tools.
    """
    if not time_str:
        time_str = datetime.now().strftime("%H:%M")

    if system_status is not None:
        health = format_health_summary(system_status)
    else:
        health = "System status is available on request."

    lang_clause = (
        f" Speak this greeting in {lang}, then follow the user's own language from their first reply onward."
        if lang.strip() else ""
    )
    user_name = name.strip() if name and name.strip() else "Sir"
    name_clause = f" Address the user as {user_name}."

    session_clause = ""
    if last_session and isinstance(last_session, dict) and last_session.get("summary"):
        summary = last_session.get("summary", "").strip()
        date_str = last_session.get("date", "")
        _when = "last time"
        if date_str:
            try:
                _delta = (datetime.now() - datetime.strptime(date_str, "%Y-%m-%d")).days
                if _delta == 0:
                    _when = "earlier today"
                elif _delta == 1:
                    _when = "yesterday"
                elif _delta > 1:
                    _when = f"{_delta} days ago"
            except Exception:
                _when = "last time"
        session_clause = f" Also briefly and naturally mention that {_when}: {summary}."

    if pending_tasks is None:
        try:
            from memory.memory_manager import get_active_pending_tasks
            pending_tasks = get_active_pending_tasks()
        except Exception:
            pending_tasks = []

    task_clause = ""
    if pending_tasks:
        descs = [t.get("description", "").strip() for t in pending_tasks if t.get("description")]
        if descs:
            task_clause = f" You also have pending tasks from previous session: {'; '.join(descs[:2])}. Briefly ask if they would like to continue them."

    greeting = (
        f"[STARTUP_GREETING] Greet {user_name} warmly, addressing them directly as '{user_name}' "
        f"(for example: 'Good morning, {user_name}' or 'Good evening, {user_name}'), "
        f"mention that it is {time_str}, "
        f"and give a short natural summary of this local system snapshot: {health}."
        f"{session_clause}{task_clause} Keep it to two or three short sentences. Do not fetch news, browse, "
        f"call tools, or mention unavailable data.{lang_clause}{name_clause}"
    )

    return greeting.strip()
