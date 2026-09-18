"""
actions/bias_detector.py — ARC Cognitive Bias & Fairness Auditor.

Evaluates text, communication drafts, or model responses for unconscious bias:
  - Gender & demographic stereotyping
  - Socioeconomic & age-based assumptions
  - Sentiment polarization & loaded rhetoric
  - Proposes balanced, inclusive, neutral alternative phrasings
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_BIAS_INDICATORS = [
    {
        "category": "Gender Stereotyping",
        "patterns": [
            (r"\b(bossy|hysterical|feisty|emotional)\b", "Loaded emotional characterizations disproportionately applied across gender lines."),
            (r"\b(man up|grow a pair)\b", "Toxic masculine normative tropes."),
            (r"\b(female engineer|female doctor|male nurse)\b", "Unnecessary gender qualifiers assuming default demographic roles."),
        ],
    },
    {
        "category": "Age & Generational Bias",
        "patterns": [
            (r"\b(too old to learn|tech-illiterate senior|grandpa tech)\b", "Generalizations attributing technological incompetence to older adults."),
            (r"\b(lazy millennial|entitled gen-z)\b", "Derogatory generational generalizations."),
        ],
    },
    {
        "category": "Absolute & Polarized Rhetoric",
        "patterns": [
            (r"\b(always|never|completely useless|utterly corrupt|obviously idiots)\b", "Hyperbolic polarized absolutes that suppress nuanced perspective."),
            (r"\b(everybody knows that|it's simple common sense that)\b", "Epistemic closure assertions dismissing counter-evidence."),
        ],
    },
    {
        "category": "Socioeconomic & Elitist Bias",
        "patterns": [
            (r"\b(unskilled labor|low-class|ghetto|trailer park)\b", "Classist framing marginalizing specific socioeconomic groups."),
        ],
    },
]


def _evaluate_bias(text: str) -> Dict[str, Any]:
    """Calculates bias index score and flags specific terms."""
    found_flags = []
    text_lower = text.lower()

    for group in _BIAS_INDICATORS:
        cat = group["category"]
        for pat, explanation in group["patterns"]:
            matches = re.findall(pat, text_lower)
            if matches:
                found_flags.append({
                    "category": cat,
                    "matched": list(set(matches)),
                    "explanation": explanation,
                })

    word_count = max(1, len(text.split()))
    match_count = sum(len(f["matched"]) for f in found_flags)

    # Score from 0.0 (perfectly balanced/neutral) to 1.0 (heavily biased)
    bias_score = min(1.0, round((match_count * 2.5) / (word_count ** 0.5), 2))

    return {
        "bias_score": bias_score,
        "flags": found_flags,
        "word_count": word_count,
    }


def bias_detector(parameters: dict, player=None, **_context) -> str:
    """Audit content for demographic, generational, or polarized rhetoric bias."""
    content = parameters.get("content", parameters.get("text", "")).strip()

    if not content:
        return "Sir, please provide the text or excerpt you would like ARC to audit for bias."

    audit = _evaluate_bias(content)
    score = audit["bias_score"]
    flags = audit["flags"]

    if score < 0.15 and not flags:
        status_badge = "🟢 Objective & Neutral (Low Bias Risk)"
        breakdown = "No significant loaded demographic stereotypes or polarized rhetorical patterns were detected."
        suggestions = "The text demonstrates balanced, objective phrasing."
    elif score < 0.45:
        status_badge = "🟡 Moderate Polarization / Minor Loaded Terms"
        lines = []
        for f in flags:
            lines.append(f"• **{f['category']}**: Identified terms `{', '.join(f['matched'])}` — {f['explanation']}")
        breakdown = "\n".join(lines)
        suggestions = "Consider substituting loaded emotional adjectives with factual behavioral descriptions."
    else:
        status_badge = "🔴 High Bias / Polarized Indicators Detected"
        lines = []
        for f in flags:
            lines.append(f"• **{f['category']}**: Identified terms `{', '.join(f['matched'])}` — {f['explanation']}")
        breakdown = "\n".join(lines)
        suggestions = "Reframe absolute generalizations (e.g. 'always', 'never') and remove demographic-linked qualifiers."

    return (
        f"⚖️ ARC Cognitive Bias & Fairness Audit:\n\n"
        f"Bias Score: **{score:.2f} / 1.00** | Assessment: {status_badge}\n\n"
        f"Detected Patterns:\n{breakdown}\n\n"
        f"Recommendation for Neutral Framing:\n{suggestions}"
    )


TOOL = {
    "name": "bias_detector",
    "description": (
        "ARC Cognitive Bias and Fairness Auditor. Analyzes written content for demographic, "
        "generational, socioeconomic, or emotionally polarized bias, computes a bias score (0-1), "
        "and provides neutral, balanced re-phrasing recommendations."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "content": {
                "type": "STRING",
                "description": "The text or statement to analyze for cognitive and demographic bias",
            },
        },
        "required": ["content"],
    },
    "handler": bias_detector,
}
