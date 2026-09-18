"""
actions/document_intelligence.py — ARC Legal & Contract Document Intelligence Agent.

Ingests legal agreements and contracts (PDF, DOCX, TXT):
- Extracts and classifies clauses (Obligations, Rights, Liabilities, Termination, Confidentiality,
  Payment Terms, Warranties, Intellectual Property).
- Scores clause risks (HIGH, MEDIUM, LOW) based on unbounded liabilities, asymmetric terms,
  unilateral termination, or ambiguous language.
- Audits missing standard protective clauses (Limitation of Liability, Force Majeure,
  Governing Law, Severability, Entire Agreement, Data Privacy).
- Synthesizes executive risk matrix and redline recommendations via Gemini API with
  heuristic fallback.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Optional document parsing libraries
try:
    import pypdf
    _PYPDF_AVAILABLE = True
except ImportError:
    _PYPDF_AVAILABLE = False

try:
    import docx
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False


# ── Text Extraction ──────────────────────────────────────────────────────────

def _extract_text_from_file(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        if not _PYPDF_AVAILABLE:
            raise RuntimeError("pypdf is required to parse PDF documents.")
        reader = pypdf.PdfReader(str(file_path))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- Page {i+1} ---\n{text}")
        return "\n\n".join(pages)

    elif ext in (".docx", ".doc"):
        if not _DOCX_AVAILABLE:
            raise RuntimeError("python-docx is required to parse DOCX documents.")
        doc = docx.Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)

    elif ext in (".txt", ".md", ".rtf", ".json", ".csv"):
        return file_path.read_text(encoding="utf-8", errors="replace")
    else:
        # Fallback to UTF-8 read
        return file_path.read_text(encoding="utf-8", errors="replace")


# ── Heuristic Clause Extraction & Classification ─────────────────────────────

CLAUSE_CATEGORIES = {
    "Liabilities & Indemnification": [
        r"\bindemn(?:ify|ification|ity)\b",
        r"\bliab(?:le|ility)\b",
        r"\bdamages\b",
        r"\bhold harmless\b",
        r"\bloss(?:es)?\b",
    ],
    "Termination & Suspension": [
        r"\bterminat(?:e|ion|ed)\b",
        r"\bcure period\b",
        r"\bfor convenience\b",
        r"\bbreach\b",
        r"\bnotice of default\b",
    ],
    "Confidentiality & Non-Disclosure": [
        r"\bconfidenti(?:al|ality)\b",
        r"\bnon-disclosure\b",
        r"\bproprietary information\b",
        r"\btrade secret\b",
    ],
    "Intellectual Property": [
        r"\bintellectual property\b",
        r"\bpatent|copyright|trademark\b",
        r"\bwork for hire\b",
        r"\bownership of work product\b",
        r"\bassignment of rights\b",
        r"\blicens(?:e|or|ee)\b",
    ],
    "Payment & Commercial Terms": [
        r"\bpayment terms?\b",
        r"\binvoic(?:e|ing)\b",
        r"\bfee(?:s)?\b",
        r"\bnet\s+(?:15|30|45|60|90)\b",
        r"\blate interest\b",
        r"\btax(?:es)?\b",
    ],
    "Warranties & Disclaimers": [
        r"\bwarrant(?:y|ies)\b",
        r"\brepresentation(?:s)?\b",
        r"\bas is\b",
        r"\bdisclaimer\b",
        r"\bmerchantability\b",
        r"\bfitness for a particular purpose\b",
    ],
    "Obligations & Covenants": [
        r"\bshall\b",
        r"\bcovenant\b",
        r"\bmust\b",
        r"\bagrees to perform\b",
        r"\bduties\b",
    ],
    "Rights & Remedies": [
        r"\bshall have the right\b",
        r"\bentitled to\b",
        r"\bsole discretion\b",
        r"\bremed(?:y|ies)\b",
    ],
}

STANDARD_PROTECTIONS = [
    ("Limitation of Liability", r"\blimitation of liability\b|\bliability cap\b|\baggregate liability\b|\bshall not exceed\b"),
    ("Force Majeure", r"\bforce majeure\b|\bact of god\b|\bunforeseeable circumstances\b"),
    ("Governing Law & Jurisdiction", r"\bgoverning law\b|\bjurisdiction\b|\bchoice of law\b|\bvenue\b"),
    ("Severability", r"\bseverability\b|\binvalidity of any provision\b"),
    ("Entire Agreement / Integration", r"\bentire agreement\b|\bsupersedes\b|\bmerger clause\b"),
    ("Data Protection & Privacy", r"\bdata protection\b|\bgdpr\b|\bprivacy policy\b|\bpersonal data\b"),
]


def _extract_clauses(text: str) -> List[Dict[str, Any]]:
    # Split text into paragraphs/sections
    chunks = [c.strip() for c in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if len(c.strip()) > 40]
    classified_clauses = []

    for i, chunk in enumerate(chunks):
        matched_category = "General Provisions"
        for cat, patterns in CLAUSE_CATEGORIES.items():
            if any(re.search(pat, chunk, re.IGNORECASE) for pat in patterns):
                matched_category = cat
                break

        # Risk scoring heuristic
        risk = "LOW"
        reasons = []

        chunk_lower = chunk.lower()
        if "unlimited liability" in chunk_lower or ("indemnify" in chunk_lower and "without limitation" in chunk_lower):
            risk = "HIGH"
            reasons.append("Uncapped / unlimited liability or indemnity obligation.")
        elif "sole discretion" in chunk_lower and "terminate" in chunk_lower:
            risk = "HIGH"
            reasons.append("Unilateral termination right at counterparty's sole discretion.")
        elif "perpetual" in chunk_lower and ("license" in chunk_lower or "confidential" in chunk_lower):
            risk = "MEDIUM"
            reasons.append("Perpetual obligation or irrevocable license grant.")
        elif "exclusive remedy" in chunk_lower or "waives any right to" in chunk_lower:
            risk = "MEDIUM"
            reasons.append("Waiver of claims or exclusive restrictive remedy.")
        elif matched_category in ("Liabilities & Indemnification", "Intellectual Property") and ("all claims" in chunk_lower or "irrevocable" in chunk_lower):
            risk = "HIGH"
            reasons.append("Broad non-standard exposure in critical legal clause.")

        if matched_category != "General Provisions" or risk != "LOW":
            classified_clauses.append({
                "index": i + 1,
                "category": matched_category,
                "snippet": chunk[:280] + ("..." if len(chunk) > 280 else ""),
                "full_text": chunk,
                "risk": risk,
                "reasons": reasons,
            })

    return classified_clauses


def _audit_standard_protections(text: str) -> Dict[str, bool]:
    audit_results = {}
    for name, pattern in STANDARD_PROTECTIONS:
        found = bool(re.search(pattern, text, re.IGNORECASE))
        audit_results[name] = found
    return audit_results


# ── LLM Synthesis ────────────────────────────────────────────────────────────

def _synthesize_with_gemini(text: str, clauses: List[Dict[str, Any]], audit: Dict[str, bool]) -> Optional[str]:
    from memory.config_manager import get_api_key
    api_key = get_api_key("gemini")
    if not api_key:
        return None

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        prompt = (
            "You are ARC Document Intelligence, an expert contract attorney and legal risk analyst.\n"
            "Analyze the following agreement. Provide a structured review formatted in Markdown:\n\n"
            "### 1. Executive Summary & Overall Risk Rating (HIGH / MEDIUM / LOW)\n"
            "### 2. Key Clause Classifications & Risk Matrix (Category, Summary, Risk Level, Risk Rationale)\n"
            "### 3. Missing Standard Protections Audit\n"
            "### 4. Actionable Negotiation Recommendations & Redlines\n\n"
            f"Pre-extracted high/medium risk candidate clauses: {json.dumps([c for c in clauses if c['risk'] in ('HIGH', 'MEDIUM')][:10])}\n\n"
            f"Pre-audited protection flags: {json.dumps(audit)}\n\n"
            f"Document excerpt:\n{text[:6000]}"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"[DocumentIntelligence] Gemini synthesis note: {e}")
    return None


# ── Action Handler ───────────────────────────────────────────────────────────

def document_intelligence(parameters: dict, player=None, **_context) -> str:
    """Analyze contracts, agreements, or legal texts for risks, clauses, and missing protections."""
    raw_path = parameters.get("path") or parameters.get("file_path") or parameters.get("file")
    raw_text = parameters.get("text")

    doc_text = ""
    source_name = "Direct Input"

    if raw_path:
        p = Path(raw_path).expanduser().resolve()
        if not p.exists() or not p.is_file():
            return f"Error: Specified file does not exist: '{p}'"
        source_name = p.name
        try:
            doc_text = _extract_text_from_file(p)
        except Exception as e:
            return f"Error extracting text from '{p}': {e}"
    elif raw_text:
        doc_text = str(raw_text).strip()
    else:
        return "Please provide either 'path' (to a PDF/DOCX/TXT file) or 'text' of the agreement."

    if not doc_text.strip():
        return "The document contains no readable text."

    clauses = _extract_clauses(doc_text)
    audit = _audit_standard_protections(doc_text)

    # Try Gemini synthesis
    gemini_analysis = _synthesize_with_gemini(doc_text, clauses, audit)

    if gemini_analysis:
        output_report = f"# ARC Document Intelligence Review: {source_name}\n\n{gemini_analysis}"
    else:
        # Structured Heuristic Fallback Report
        high_risks = [c for c in clauses if c["risk"] == "HIGH"]
        med_risks = [c for c in clauses if c["risk"] == "MEDIUM"]
        overall = "HIGH" if high_risks else ("MEDIUM" if med_risks else "LOW")

        missing = [k for k, v in audit.items() if not v]
        present = [k for k, v in audit.items() if v]

        lines = [
            f"# ARC Document Intelligence Review: {source_name}",
            f"**Overall Risk Rating:** {overall}",
            f"**Total Classified Clauses:** {len(clauses)} | **High Risk:** {len(high_risks)} | **Medium Risk:** {len(med_risks)}",
            "",
            "## 1. Missing Protections Audit",
        ]
        if missing:
            lines.append(f"⚠️ **Missing Essential Safeguards:** {', '.join(missing)}")
        else:
            lines.append("✅ All standard essential protections detected.")
        lines.append(f"✓ Detected Protections: {', '.join(present) if present else 'None'}")
        lines.append("")

        lines.append("## 2. Critical & Elevated Risk Clauses")
        flagged = high_risks + med_risks
        if not flagged:
            lines.append("No immediate high or medium risk liabilities detected via heuristic scan.")
        else:
            for c in flagged[:8]:
                lines.append(f"### [{c['risk']}] {c['category']}")
                lines.append(f"> \"{c['snippet']}\"")
                if c["reasons"]:
                    lines.append(f"**Flags:** {'; '.join(c['reasons'])}")
                lines.append("")

        lines.append("## 3. Actionable Negotiation Points")
        if "Limitation of Liability" in missing:
            lines.append("- **Insert Liability Cap:** Add mutual limitation of liability capped at aggregate 12-month fees.")
        if "Force Majeure" in missing:
            lines.append("- **Add Force Majeure:** Protect against unforeseen catastrophic operational interruptions.")
        if high_risks:
            lines.append("- **Narrow Indemnities:** Ensure indemnification is strictly tied to third-party IP infringement, not broad gross negligence.")

        output_report = "\n".join(lines)

    # Update HUD if available
    try:
        if player and hasattr(player, "ui") and hasattr(player.ui, "show_content"):
            player.ui.show_content(f"Doc Intel: {source_name[:24]}", output_report[:3800])
    except Exception:
        pass

    return output_report


TOOL = {
    "name": "document_intelligence",
    "description": (
        "Ingest and analyze legal agreements and contracts (PDF, DOCX, TXT). Extracts and classifies "
        "clauses (obligations, liabilities, termination, IP, payment), scores risk levels (HIGH, MED, LOW), "
        "audits missing standard protections, and provides redline negotiation recommendations."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "Path to document file (PDF, DOCX, TXT, MD)",
            },
            "text": {
                "type": "STRING",
                "description": "Direct contract text if no file path is provided",
            },
        },
    },
    "handler": document_intelligence,
}
