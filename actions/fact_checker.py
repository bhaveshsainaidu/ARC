"""
actions/fact_checker.py — ARC Autonomous Multi-Source Fact Checking & Truth Verification Agent.

Deconstructs claims into verifiable sub-assertions, queries multi-source evidence
(Wikipedia API, DuckDuckGo Search, Gemini Google Search grounding), scores source credibility,
calculates consensus indices, and produces structured truth audits.

Verdict Ratings:
- TRUE
- MOSTLY TRUE
- MIXED
- MOSTLY FALSE
- FALSE
- UNVERIFIED
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


# ── Wikipedia API Search ─────────────────────────────────────────────────────

def _search_wikipedia(query: str, limit: int = 3) -> List[Dict[str, str]]:
    results = []
    try:
        url = (
            "https://en.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={urllib.parse.quote(query)}&utf8=&format=json&srlimit={limit}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "ARC-Agent/2.0 (FactChecker; mailto:contact@arc.ai)"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for item in data.get("query", {}).get("search", []):
                snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                title = item.get("title", "")
                page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                results.append({
                    "source": "Wikipedia",
                    "title": title,
                    "snippet": snippet,
                    "url": page_url,
                    "credibility": 0.85,
                })
    except Exception as e:
        print(f"[FactChecker] Wikipedia query error: {e}")
    return results


# ── DuckDuckGo Search ────────────────────────────────────────────────────────

def _search_ddg(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    results = []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=limit):
                url = r.get("href", "")
                cred = 0.70
                if any(dom in url for dom in (".gov", ".edu", "reuters.com", "apnews.com", "bbc.co", "nature.com", "who.int", "cdc.gov", "nasa.gov")):
                    cred = 0.95
                elif any(dom in url for dom in ("theguardian.com", "nytimes.com", "wsj.com", "bloomberg.com", "economist.com", "arxiv.org")):
                    cred = 0.90

                results.append({
                    "source": "Web / DuckDuckGo",
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": url,
                    "credibility": cred,
                })
    except Exception as e:
        print(f"[FactChecker] DDG search error: {e}")
    return results


# ── Gemini Grounded Verification ─────────────────────────────────────────────

def _verify_with_gemini(claim: str, evidence: List[Dict[str, Any]]) -> Optional[str]:
    from memory.config_manager import get_api_key
    api_key = get_api_key("gemini")
    if not api_key:
        return None

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        evidence_text = "\n\n".join(
            f"Source [{e['source']} - {e['title']}] ({e.get('url')} | Credibility: {e.get('credibility')}):\n{e['snippet']}"
            for e in evidence
        )

        prompt = (
            "You are ARC Fact Checker, an elite adversarial epistemological auditor.\n"
            "Analyze the target claim against established empirical evidence and logic.\n\n"
            f"TARGET CLAIM: \"{claim}\"\n\n"
            f"RETRIEVED MULTI-SOURCE EVIDENCE:\n{evidence_text if evidence_text else 'None retrieved directly from local index.'}\n\n"
            "Provide an exhaustive, objective breakdown formatted in Markdown:\n"
            "### 1. Definitive Verdict\n"
            "Choose EXACTLY ONE: [TRUE | MOSTLY TRUE | MIXED | MOSTLY FALSE | FALSE | UNVERIFIED]\n"
            "- Consensus Index (0% to 100% agreement across authoritative sources)\n"
            "- Overall Source Credibility Score (0.0 to 1.0)\n\n"
            "### 2. Sub-Assertion Deconstruction\n"
            "Break down the claim into 2-4 granular propositions and evaluate each individually.\n\n"
            "### 3. Fallacy & Manipulation Audit\n"
            "- Flag logical fallacies (cherry-picking, post hoc, false dichotomy, straw man, ad hominem).\n"
            "- Temporal Decay: Is this claim outdated or superseded by recent discoveries/events?\n"
            "- Statistical Distortion: Are raw numbers presented without per-capita or baseline context?\n\n"
            "### 4. Authoritative Citations & Summary Synthesis\n"
            "Cite verifiable facts and clear consensus conclusions."
        )

        # Attempt search grounding if enabled
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={"tools": [{"google_search": {}}]},
            )
        except Exception:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )

        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"[FactChecker] Gemini verification error: {e}")
    return None


# ── Heuristic Analysis Fallback ──────────────────────────────────────────────

def _heuristic_verification(claim: str, evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return (
            f"# ARC Fact Checker Report: \"{claim}\"\n\n"
            "### Verdict: UNVERIFIED\n"
            "- **Consensus Index:** N/A\n"
            "- **Source Credibility:** N/A\n\n"
            "**Reasoning:** Insufficient independent external records or network connectivity "
            "to establish multi-source corroboration."
        )

    # Calculate average credibility
    avg_cred = sum(e.get("credibility", 0.5) for e in evidence) / max(len(evidence), 1)

    lines = [
        f"# ARC Fact Checker Report: \"{claim}\"",
        "",
        "### 1. Evidence Overview",
        f"- **Total Independent Sources Examined:** {len(evidence)}",
        f"- **Average Source Credibility Index:** {avg_cred:.2f} / 1.00",
        "",
        "### 2. Discovered Evidence Highlights",
    ]
    for i, e in enumerate(evidence[:5]):
        lines.append(f"**[{i+1}] {e['title']}** ({e['source']} - Cred: {e.get('credibility', 0.5):.2f})")
        lines.append(f"> {e['snippet'][:250]}...")
        if e.get("url"):
            lines.append(f"Link: {e['url']}")
        lines.append("")

    lines.append("### 3. Epistemic Assessment")
    lines.append(
        "Based on multi-source evidence extraction, review retrieved data against claim assertions. "
        "High authoritative domain representation indicates reliable cross-reference baseline."
    )
    return "\n".join(lines)


# ── Action Handler ───────────────────────────────────────────────────────────

def fact_checker(parameters: dict, player=None, **_context) -> str:
    """Verify factual assertions against multi-source evidence, scoring credibility and consensus."""
    claim = str(parameters.get("claim") or parameters.get("query") or parameters.get("statement") or "").strip()
    if not claim:
        return "Error: Please specify the 'claim' or statement to verify."

    # Gather evidence across Wikipedia and DuckDuckGo
    wiki_evidence = _search_wikipedia(claim, limit=3)
    ddg_evidence = _search_ddg(claim, limit=4)
    all_evidence = wiki_evidence + ddg_evidence

    # Run Gemini verification if possible
    analysis = _verify_with_gemini(claim, all_evidence)
    if not analysis:
        analysis = _heuristic_verification(claim, all_evidence)

    # Display on HUD if available
    try:
        if player and hasattr(player, "ui") and hasattr(player.ui, "show_content"):
            player.ui.show_content(f"Fact Check: {claim[:24]}", analysis[:3800])
    except Exception:
        pass

    return analysis


TOOL = {
    "name": "fact_checker",
    "description": (
        "Deconstruct claims into testable assertions, gather multi-source evidence (Wikipedia, DuckDuckGo, "
        "authoritative web sources), calculate source credibility and consensus index, detect fallacies and "
        "temporal decay, and provide an authoritative truth verdict (TRUE, MOSTLY TRUE, MIXED, FALSE, UNVERIFIED)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "claim": {
                "type": "STRING",
                "description": "The specific claim, statistic, or assertion to fact-check and verify.",
            },
        },
        "required": ["claim"],
    },
    "handler": fact_checker,
}
