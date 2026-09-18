"""
actions/transparency_report.py — ARC Explainability & Decision Transparency Engine.

Generates plain-English, human-readable transparency and audit reports explaining:
  - Why specific autonomous decisions and tool invocations occurred
  - Blocked commands and ethical guardrail triggers
  - Data access events and permission checks
  - Saves comprehensive audit logs to outputs/transparency/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_output_dir() -> Path:
    out_dir = _get_base_dir() / "outputs" / "transparency"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def transparency_report(parameters: dict, player=None, **_context) -> str:
    """Generate an audit report detailing ARC autonomous decisions, tool calls, and ethical checks."""
    timeframe = parameters.get("timeframe", "recent").lower().strip()
    save_file = parameters.get("save_file", True)

    audit_path = _get_base_dir() / "memory" / "ethical_audit.json"
    entries: List[Dict[str, Any]] = []

    if audit_path.exists():
        try:
            entries = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            entries = []

    total_events = len(entries)
    allowed_count = sum(1 for e in entries if e.get("decision") == "ALLOWED")
    blocked_count = sum(1 for e in entries if e.get("decision") == "BLOCKED")
    alert_count = sum(1 for e in entries if e.get("decision") in ("ALERT", "REQUIRES_CONSENT"))

    # Recent 10 events
    recent_events = entries[-10:] if entries else []
    recent_lines = []
    for ev in reversed(recent_events):
        badge = "🟢" if ev.get("decision") == "ALLOWED" else "🛑"
        ts = ev.get("timestamp", "").split("T")[-1][:8]
        recent_lines.append(
            f"• [{ts}] {badge} **{ev.get('action')}** ({ev.get('decision')}): {ev.get('rationale')}"
        )

    recent_table = "\n".join(recent_lines) if recent_lines else "No audit events recorded yet."

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_content = f"""# ARC Autonomous Decision Transparency & Audit Report
**Generated On**: {now_str}
**Auditor**: ARC Ethical Framework v4.0
**Scope**: User Local Session Integrity

---

## 1. Executive Telemetry Summary
- **Total Audited Actions**: {total_events}
- **Authorized / Compliant Events**: {allowed_count}
- **Blocked Disallowed Actions**: {blocked_count}
- **Privacy & PII Sensitive Alerts**: {alert_count}

## 2. Guardrail Enforcement Principles
Every tool call and user directive dispatched through ARC is subject to three non-negotiable ethical constraints:
1. **Harm Minimization**: All system shell invocations and filesystem edits are evaluated against destructive patterns.
2. **Data Boundary Protection**: Outbound web searches and remote commands are sanitized to prevent PII leakage.
3. **Sovereign User Control**: All actions operate strictly under the active permissions matrix defined in `config/consents.json`.

## 3. Recent Decision Trace Log
{recent_table}

---
*Report generated automatically for verifiable transparency.*
"""

    file_msg = ""
    if save_file:
        out_dir = _get_output_dir()
        ts_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = out_dir / f"{ts_slug}_transparency_report.md"
        report_file.write_text(report_content, encoding="utf-8")
        file_msg = f"\n📁 Complete transparency report exported to: {report_file}"

    return (
        f"📊 ARC Transparency & Explainability Report:\n\n"
        f"Audited Actions: {total_events} | Allowed: {allowed_count} | Blocked: {blocked_count} | PII Alerts: {alert_count}\n\n"
        f"Recent Key Decisions:\n{recent_table}{file_msg}"
    )


TOOL = {
    "name": "transparency_report",
    "description": (
        "ARC Explainability & Decision Transparency tool. Produces plain-English audit reports "
        "explaining why actions were executed, blocked, or guarded by the ethical safety framework."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "timeframe": {
                "type": "STRING",
                "description": "Report scope: 'recent', 'daily', or 'all' (default: recent)",
            },
            "save_file": {
                "type": "BOOLEAN",
                "description": "Whether to export the markdown report to disk (default: true)",
            },
        },
        "required": [],
    },
    "handler": transparency_report,
}
