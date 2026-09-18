"""
actions/complaint_triage.py — ARC Autonomous Customer Complaint, Feedback & Ticket Triage Agent.

Ingests user feedback, customer support tickets, and bug reports (raw text, CSV, JSON).
- Classifies by department: Engineering/Bug, Billing, Product/Feature, Support, Legal/Compliance.
- Computes Urgency & Priority Scoring: P0 Blocker, P1 Critical, P2 High, P3 Medium, P4 Low.
- Clusters and deduplicates recurring incident patterns.
- Generates department routing, recommended owner assignments, and tailored customer response drafts.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Ingestion Helpers ────────────────────────────────────────────────────────

def _parse_input_data(text: Optional[str], path: Optional[str]) -> List[Dict[str, Any]]:
    tickets = []
    if path:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"File not found: {p}")

        ext = p.suffix.lower()
        content = p.read_text(encoding="utf-8", errors="replace")

        if ext == ".json":
            data = json.loads(content)
            if isinstance(data, list):
                tickets = data
            elif isinstance(data, dict):
                tickets = data.get("tickets") or data.get("issues") or [data]
        elif ext == ".csv":
            reader = csv.DictReader(io.StringIO(content))
            for i, row in enumerate(reader):
                tickets.append({
                    "id": row.get("id") or row.get("ticket_id") or f"TCK-{i+1:03d}",
                    "text": row.get("description") or row.get("text") or row.get("message") or " ".join(row.values()),
                    "tier": row.get("tier") or row.get("customer_tier") or "Standard",
                    "author": row.get("author") or row.get("user") or row.get("email") or "Customer",
                })
        else:
            # Plain text: split by lines or blocks
            blocks = [b.strip() for b in re.split(r"\n\s*\n|---+", content) if b.strip()]
            for i, block in enumerate(blocks):
                tickets.append({"id": f"TCK-{i+1:03d}", "text": block, "tier": "Standard", "author": "User"})

    elif text:
        # Check if text is JSON string
        stripped = text.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get("tickets") or [data]
            except Exception:
                pass

        blocks = [b.strip() for b in re.split(r"\n\s*\n|---+", stripped) if b.strip()]
        for i, block in enumerate(blocks):
            tickets.append({"id": f"TCK-{i+1:03d}", "text": block, "tier": "Standard", "author": "Customer"})

    return tickets


# ── Rule-Based Categorization & Scoring ──────────────────────────────────────

DEPARTMENT_PATTERNS = {
    "Engineering / Bug": [
        r"\berror\b", r"\bbug\b", r"\bcrash(?:ed|es)?\b", r"\bexception\b", r"\b500\b",
        r"\btraceback\b", r"\bfailed to load\b", r"\bfreeze\b", r"\btimeout\b", r"\bbroken\b",
    ],
    "Billing & Commercial": [
        r"\bcharg(?:e|ed|ing)\b", r"\binvoice\b", r"\brefund\b", r"\bovercharg(?:e|ed)\b",
        r"\bcredit card\b", r"\bsubscription\b", r"\bpayment\b", r"\bpricing\b", r"\bbill\b",
    ],
    "Product / Feature Request": [
        r"\bfeature request\b", r"\bwould love\b", r"\bplease add\b", r"\bsuggest(?:ion)?\b",
        r"\bimprove(?:ment)?\b", r"\broadmap\b", r"\benhancement\b",
    ],
    "Legal, Compliance & Security": [
        r"\bgdpr\b", r"\bprivacy\b", r"\bbreach\b", r"\bvulnerab(?:le|ility)\b", r"\bexploit\b",
        r"\bcompliance\b", r"\blegal\b", r"\bterms of service\b", r"\bdata leak\b",
    ],
    "Support & Operations": [
        r"\bhow do i\b", r"\bhelp\b", r"\bcannot find\b", r"\bdocumentation\b", r"\bsetup\b",
        r"\blogin\b", r"\bpassword reset\b", r"\bguide\b", r"\bonboarding\b",
    ],
}


def _triage_ticket(ticket: Dict[str, Any]) -> Dict[str, Any]:
    raw_text = str(ticket.get("text") or ticket.get("description") or ticket.get("message") or "")
    text_lower = raw_text.lower()
    tier = str(ticket.get("tier", "Standard")).capitalize()

    # 1. Department match
    matched_dept = "Support & Operations"
    for dept, patterns in DEPARTMENT_PATTERNS.items():
        if any(re.search(pat, text_lower) for pat in patterns):
            matched_dept = dept
            break

    # 2. Priority scoring
    is_vip = tier in ("Enterprise", "Vip", "Tier 1", "Platinum", "Gold")
    has_blocker_word = any(w in text_lower for w in ("outage", "down", "data loss", "security breach", "cannot access account", "production", "critical"))
    has_urgency_word = any(w in text_lower for w in ("asap", "urgent", "immediately", "furious", "unacceptable", "cancelling"))

    if has_blocker_word or (is_vip and has_urgency_word) or matched_dept == "Legal, Compliance & Security":
        priority = "P0 - Blocker"
        sla = "1 Hour"
    elif has_urgency_word or (is_vip and matched_dept in ("Engineering / Bug", "Billing & Commercial")):
        priority = "P1 - Critical"
        sla = "4 Hours"
    elif matched_dept in ("Engineering / Bug", "Billing & Commercial"):
        priority = "P2 - High"
        sla = "24 Hours"
    elif matched_dept == "Support & Operations":
        priority = "P3 - Medium"
        sla = "48 Hours"
    else:
        priority = "P4 - Low"
        sla = "5 Business Days"

    # 3. Routing owner
    routing_map = {
        "Engineering / Bug": "Core Platform & Infrastructure Team",
        "Billing & Commercial": "Finance Operations & Billing Support",
        "Product / Feature Request": "Product Management & UX Guild",
        "Legal, Compliance & Security": "InfoSec & Compliance Counsel",
        "Support & Operations": "Tier 2 Customer Support",
    }
    owner = routing_map.get(matched_dept, "Customer Operations")

    # 4. Draft response template
    first_sentence = raw_text.split(".")[0] if raw_text else "your inquiry"
    draft = (
        f"Hello {ticket.get('author', 'Valued Customer')},\n\n"
        f"Thank you for contacting us regarding {first_sentence.lower()}. "
        f"We understand the importance of this matter and have escalated this ticket to our {owner} "
        f"with priority {priority.split(' - ')[0]}.\n\n"
        f"A specialist is actively investigating and will follow up with resolution details within {sla}.\n\n"
        f"Best regards,\nARC Support Escalations"
    )

    return {
        "id": ticket.get("id", "TCK-001"),
        "author": ticket.get("author", "Customer"),
        "tier": tier,
        "department": matched_dept,
        "priority": priority,
        "sla": sla,
        "owner": owner,
        "draft_response": draft,
        "summary": raw_text[:140] + ("..." if len(raw_text) > 140 else ""),
    }


# ── LLM Synthesis Option ─────────────────────────────────────────────────────

def _synthesize_triage_gemini(tickets: List[Dict[str, Any]]) -> Optional[str]:
    from memory.config_manager import get_api_key
    api_key = get_api_key("gemini")
    if not api_key:
        return None

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        sample = tickets[:15]
        prompt = (
            "You are ARC Complaint Triage & Customer Intelligence Agent.\n"
            "Analyze and triage the following support tickets / complaints.\n"
            "Produce an executive triage report in Markdown:\n\n"
            "### 1. Executive Triage Summary & Urgency Distribution (P0, P1, P2, P3, P4 breakdown)\n"
            "### 2. Department Routing & Incident Clustering (identify duplicates and recurring failure modes)\n"
            "### 3. High-Priority Ticket Manifest (ID, Customer Tier, Department, Root Cause Hypothesis, Assignee)\n"
            "### 4. Empathetic Customer Response Drafts (for top 2 critical tickets)\n"
            "### 5. Preventative Action Items for Product/Engineering\n\n"
            f"Tickets Data:\n{json.dumps(sample, indent=2)}"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"[ComplaintTriage] Gemini synthesis error: {e}")
    return None


# ── Action Handler ───────────────────────────────────────────────────────────

def complaint_triage(parameters: dict, player=None, **_context) -> str:
    """Ingest, prioritize, cluster, and route customer feedback and bug reports."""
    raw_text = parameters.get("text")
    raw_path = parameters.get("path") or parameters.get("file_path") or parameters.get("file")

    if not raw_text and not raw_path:
        return "Please provide either 'text' (single ticket or JSON/lines) or 'path' to a ticket file (CSV, JSON, TXT)."

    try:
        tickets_raw = _parse_input_data(raw_text, raw_path)
    except Exception as e:
        return f"Error reading ticket input: {e}"

    if not tickets_raw:
        return "No valid tickets or feedback messages could be extracted from input."

    # Try Gemini comprehensive synthesis
    gemini_report = _synthesize_triage_gemini(tickets_raw)
    if gemini_report:
        report = f"# ARC Customer Feedback & Ticket Triage Report\n\n{gemini_report}"
    else:
        # Structured local triage
        triaged = [_triage_ticket(t) for t in tickets_raw]
        p_counts = {}
        d_counts = {}
        for t in triaged:
            p = t["priority"]
            d = t["department"]
            p_counts[p] = p_counts.get(p, 0) + 1
            d_counts[d] = d_counts.get(d, 0) + 1

        lines = [
            "# ARC Customer Feedback & Ticket Triage Report",
            f"**Total Processed Tickets:** {len(triaged)}",
            "",
            "## 1. Priority Breakdown",
        ]
        for p, count in sorted(p_counts.items()):
            lines.append(f"- **{p}:** {count}")

        lines.append("\n## 2. Department Allocation")
        for d, count in sorted(d_counts.items()):
            lines.append(f"- **{d}:** {count} ticket(s)")

        lines.append("\n## 3. Prioritized Manifest (Top Critical)")
        sorted_tickets = sorted(triaged, key=lambda x: x["priority"])
        for t in sorted_tickets[:6]:
            lines.append(f"### [{t['priority']}] {t['id']} — {t['department']}")
            lines.append(f"- **Customer Tier:** {t['tier']} | **Target SLA:** {t['sla']}")
            lines.append(f"- **Owner:** {t['owner']}")
            lines.append(f"- **Summary:** {t['summary']}")
            lines.append(f"```\nResponse Draft:\n{t['draft_response']}\n```\n")

        report = "\n".join(lines)

    # Update HUD if available
    try:
        if player and hasattr(player, "ui") and hasattr(player.ui, "show_content"):
            player.ui.show_content("Ticket Triage", report[:3800])
    except Exception:
        pass

    return report


TOOL = {
    "name": "complaint_triage",
    "description": (
        "Ingest, classify, score, and route customer feedback, support tickets, and bug reports (text, CSV, JSON). "
        "Assigns priority (P0 Blocker to P4 Low), categorizes functional department (Engineering, Billing, Product, "
        "Support, Legal), clusters recurring issues, and generates tailored customer response templates."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "text": {
                "type": "STRING",
                "description": "Ticket text, JSON string, or multiline complaint feedback.",
            },
            "path": {
                "type": "STRING",
                "description": "Path to ticket file (CSV, JSON, or TXT).",
            },
        },
    },
    "handler": complaint_triage,
}
