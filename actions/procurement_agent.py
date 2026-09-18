"""
actions/procurement_agent.py — ARC Vendor RFP, Pricing Normalization & TCO Procurement Agent.

Ingests vendor quotes, RFPs, and pricing proposals (JSON, CSV, text):
- Normalizes pricing across currencies, billing periods (monthly/annual), seat tiers, and implementation fees.
- Feature Comparison Matrix: Scores vendor capabilities against requirement specifications.
- Total Cost of Ownership (TCO): Computes projected 1-Year, 3-Year, and 5-Year expenditures including
  support tiers, implementation overhead, and renewal uplifts.
- Cost-Benefit Scorecard: Produces ranked recommendations and vendor negotiation levers.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EXCHANGE_RATES_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.28,
    "INR": 0.012,
    "JPY": 0.0067,
    "CAD": 0.74,
    "AUD": 0.65,
}


def _parse_vendor_data(text: Optional[str], path: Optional[str]) -> List[Dict[str, Any]]:
    vendors = []
    if path:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"File not found: {p}")
        ext = p.suffix.lower()
        content = p.read_text(encoding="utf-8", errors="replace")

        if ext == ".json":
            data = json.loads(content)
            vendors = data if isinstance(data, list) else data.get("vendors", [data])
        elif ext == ".csv":
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                vendors.append({
                    "name": row.get("vendor") or row.get("name") or "Unknown Vendor",
                    "monthly_per_seat": float(row.get("monthly_per_seat") or row.get("price") or 0),
                    "annual_per_seat": float(row.get("annual_per_seat") or 0),
                    "seats": int(row.get("seats") or 10),
                    "setup_fee": float(row.get("setup_fee") or 0),
                    "currency": row.get("currency") or "USD",
                    "features": [f.strip() for f in (row.get("features") or "").split(";") if f.strip()],
                })
        else:
            vendors = [{"name": "Raw Proposal", "description": content}]

    elif text:
        stripped = text.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                return data if isinstance(data, list) else data.get("vendors", [data])
            except Exception:
                pass
        vendors = [{"name": "Submitted Proposal", "description": text}]

    return vendors


def _calculate_tco(vendor: Dict[str, Any], seats: int = 25) -> Dict[str, Any]:
    name = vendor.get("name", "Vendor")
    curr = str(vendor.get("currency", "USD")).upper()
    rate = EXCHANGE_RATES_TO_USD.get(curr, 1.0)

    # Base pricing
    monthly_seat = float(vendor.get("monthly_per_seat") or 0.0)
    annual_seat = float(vendor.get("annual_per_seat") or (monthly_seat * 10 if monthly_seat > 0 else 500.0))
    v_seats = int(vendor.get("seats") or seats)
    setup = float(vendor.get("setup_fee") or vendor.get("implementation_fee") or 0.0)
    support_pct = float(vendor.get("support_pct") or 0.15)  # 15% standard enterprise support

    # Normalize to USD
    annual_sub_usd = (annual_seat * v_seats) * rate
    setup_usd = setup * rate
    annual_support_usd = (annual_sub_usd * support_pct)

    # Multi-year TCO projections (assumes 4% annual inflation/renewal uplift after yr 1)
    y1_tco = setup_usd + annual_sub_usd + annual_support_usd
    y3_tco = setup_usd + (annual_sub_usd + annual_support_usd) * (1.0 + 1.04 + 1.08)
    y5_tco = setup_usd + (annual_sub_usd + annual_support_usd) * (1.0 + 1.04 + 1.08 + 1.12 + 1.16)

    return {
        "name": name,
        "currency_original": curr,
        "seats": v_seats,
        "annual_subscription_usd": round(annual_sub_usd, 2),
        "setup_fee_usd": round(setup_usd, 2),
        "annual_support_usd": round(annual_support_usd, 2),
        "tco_1yr_usd": round(y1_tco, 2),
        "tco_3yr_usd": round(y3_tco, 2),
        "tco_5yr_usd": round(y5_tco, 2),
        "features": vendor.get("features", []),
    }


def _synthesize_procurement_gemini(vendors_data: List[Dict[str, Any]], requirements: List[str]) -> Optional[str]:
    from memory.config_manager import get_api_key
    api_key = get_api_key("gemini")
    if not api_key:
        return None

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        prompt = (
            "You are ARC Procurement & Strategic Sourcing Intelligence Agent.\n"
            "Evaluate the following vendor proposals, normalized financials, and requirement criteria.\n\n"
            f"VENDORS & FINANCIAL TCO ANALYSIS:\n{json.dumps(vendors_data, indent=2)}\n\n"
            f"BUSINESS REQUIREMENTS:\n{json.dumps(requirements, indent=2) if requirements else 'Standard Enterprise Security, 99.9% SLA, API Extensibility, SSO'}\n\n"
            "Produce an executive procurement review formatted in Markdown:\n"
            "### 1. Executive Summary & Recommended Winner\n"
            "### 2. Normalized Pricing & Multi-Year TCO Matrix (1-Yr, 3-Yr, 5-Yr TCO)\n"
            "### 3. Feature Capability & Requirements Fit Scorecard\n"
            "### 4. Strategic Commercial Negotiation Levers (Discounts, Multi-Year Locking, SLA penalties)"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"[ProcurementAgent] Gemini synthesis note: {e}")
    return None


def procurement_agent(parameters: dict, player=None, **_context) -> str:
    """Analyze vendor quotes, normalize pricing, calculate multi-year TCO, and provide recommendations."""
    raw_text = parameters.get("text")
    raw_path = parameters.get("path") or parameters.get("file_path")
    reqs = parameters.get("requirements") or []
    if isinstance(reqs, str):
        reqs = [r.strip() for r in reqs.split(",") if r.strip()]

    if not raw_text and not raw_path:
        return "Please provide 'text' (quotes/RFPs) or 'path' to a vendor pricing sheet (CSV, JSON, TXT)."

    try:
        vendors_raw = _parse_vendor_data(raw_text, raw_path)
    except Exception as e:
        return f"Error reading vendor proposals: {e}"

    if not vendors_raw:
        return "No valid vendor proposals could be parsed."

    # Compute TCO models
    tco_models = [_calculate_tco(v) for v in vendors_raw]

    # Attempt Gemini strategic synthesis
    gemini_report = _synthesize_procurement_gemini(tco_models, reqs)
    if gemini_report:
        report = f"# ARC Strategic Sourcing & Procurement Evaluation\n\n{gemini_report}"
    else:
        # Structured local model
        sorted_vendors = sorted(tco_models, key=lambda x: x["tco_3yr_usd"])
        best = sorted_vendors[0]

        lines = [
            "# ARC Strategic Sourcing & Procurement Evaluation",
            f"**Recommended Vendor Selection:** {best['name']} (Lowest 3-Year TCO: ${best['tco_3yr_usd']:,.2f})",
            "",
            "## 1. Multi-Year Total Cost of Ownership (TCO) Matrix (USD)",
            "| Vendor | 1-Year TCO | 3-Year TCO | 5-Year TCO | Annual License | Setup Fee |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for v in sorted_vendors:
            lines.append(
                f"| **{v['name']}** | ${v['tco_1yr_usd']:,.2f} | ${v['tco_3yr_usd']:,.2f} | ${v['tco_5yr_usd']:,.2f} "
                f"| ${v['annual_subscription_usd']:,.2f} | ${v['setup_fee_usd']:,.2f} |"
            )

        lines.extend([
            "",
            "## 2. Procurement & Commercial Negotiation Strategy",
            f"1. **Primary Recommendation:** Award contract to **{best['name']}** for best long-term capital efficiency.",
            "2. **Discount Leverage:** Request a 15-20% multi-year commitment discount in exchange for signing a 3-year term upfront.",
            "3. **Implementation Fee Waiver:** Negotiate 100% waiver of one-time setup and onboarding fees.",
            "4. **Cap Renewal Escalation:** Require annual renewal fee escalation to be strictly capped at 3% or CPI.",
        ])
        report = "\n".join(lines)

    # Display on HUD if available
    try:
        if player and hasattr(player, "ui") and hasattr(player.ui, "show_content"):
            player.ui.show_content("Procurement TCO", report[:3800])
    except Exception:
        pass

    return report


TOOL = {
    "name": "procurement_agent",
    "description": (
        "Analyze vendor quotes, RFPs, and pricing proposals (text, CSV, JSON). Normalizes currencies and "
        "billing cycles, scores feature capabilities against requirements, projects 1-Year, 3-Year, and 5-Year "
        "Total Cost of Ownership (TCO), and generates ranked vendor scorecards with negotiation levers."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "text": {
                "type": "STRING",
                "description": "Vendor quote text, RFP details, or JSON data.",
            },
            "path": {
                "type": "STRING",
                "description": "Path to pricing spreadsheet or document (CSV, JSON, TXT).",
            },
            "requirements": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Optional list of mandatory functional requirements for scoring.",
            },
        },
    },
    "handler": procurement_agent,
}
