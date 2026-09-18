"""
actions/self_awareness.py — Self-Awareness & Capability Introspection Action Tool for ARC.
"""

from __future__ import annotations

from typing import Any, Dict
from core.self_awareness import get_self_awareness


def self_awareness(parameters: dict, **_context) -> str:
    """Action handler for answering questions about ARC's capabilities and health."""
    query = str(parameters.get("query", "what_can_you_do")).strip().lower()
    tool_name = str(parameters.get("tool_name", "")).strip()

    aware = get_self_awareness()

    if any(k in query for k in ("what can you do", "capabilities", "features", "domains")):
        return aware.what_can_you_do()
    elif any(k in query for k in ("limitation", "restrictions", "offline")):
        return aware.what_are_your_limitations()
    elif any(k in query for k in ("how many", "count", "total tools")):
        return aware.how_many_tools()
    elif any(k in query for k in ("disabled", "blocked", "inactive")):
        return aware.what_tools_are_disabled()
    elif any(k in query for k in ("describe", "explain tool", "what does")) or tool_name:
        target = tool_name or parameters.get("tool", "") or query.replace("describe", "").strip()
        return aware.describe_tool(target)
    elif any(k in query for k in ("learned about me", "memory", "know about me")):
        return aware.what_have_you_learned_about_me()
    elif any(k in query for k in ("performance", "speed", "stats", "utilization")):
        return aware.current_performance()
    elif any(k in query for k in ("diagnostics", "self check", "health", "status")):
        diag = aware.run_self_diagnostics()
        lines = ["ARC System Diagnostics:"]
        for k, v in diag.items():
            lines.append(f"  • {k.capitalize()}: {v}")
        return "\n".join(lines)
    else:
        # Default to complete capabilities summary
        return aware.what_can_you_do()


TOOL = {
    "name": "self_awareness",
    "description": (
        "Answer questions about ARC's own capabilities, loaded tools, hardware state, "
        "memory stats, performance telemetry, and system diagnostics with 100% precision."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": (
                    "Question topic: 'what_can_you_do', 'limitations', 'how_many_tools', "
                    "'disabled_tools', 'describe_tool', 'what_learned_about_me', "
                    "'performance', or 'diagnostics'."
                ),
            },
            "tool_name": {
                "type": "STRING",
                "description": "Specific tool or plugin name to describe (e.g., 'code_helper', 'cyber_shield').",
            },
        },
    },
    "handler": self_awareness,
}
