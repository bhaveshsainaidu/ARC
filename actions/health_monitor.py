"""
actions/health_monitor.py — ARC Vitals & Biometric Trend Monitoring.

Features:
  - Logs and analyzes vitals: heart rate, blood pressure, blood glucose, sleep, steps, weight
  - Automatic clinical anomaly detection (hypertension spikes, tachycardia, hypoglycemia)
  - CSV ingestion from Apple Health / Google Fit / wearable exports
  - Compiles structured Doctor Appointment Summaries
  - Encrypted storage in memory/health/vitals_log.json
  - Mandatory clinical safety disclaimers
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.health_store import MANDATORY_DISCLAIMER, load_health_data, save_health_data


def _detect_vital_anomaly(metric: str, value: Any) -> Optional[str]:
    """Evaluates biometric values against established clinical alert thresholds."""
    m = metric.lower()
    try:
        if "heart" in m or "hr" in m or "pulse" in m:
            hr = float(value)
            if hr > 110:
                return f"⚠️ Tachycardia Alert: Resting heart rate of {hr} bpm exceeds normal upper resting limits (60-100 bpm)."
            elif hr < 45:
                return f"⚠️ Bradycardia Alert: Heart rate of {hr} bpm is unusually low for non-athletic baselines."

        elif "pressure" in m or "bp" in m:
            val_str = str(value)
            if "/" in val_str:
                parts = val_str.split("/")
                sys_p = float(parts[0])
                dia_p = float(parts[1])
                if sys_p >= 180 or dia_p >= 120:
                    return f"🚨 Hypertensive Crisis Warning: BP of {val_str} mmHg requires immediate clinical attention."
                elif sys_p >= 140 or dia_p >= 90:
                    return f"⚠️ Stage 2 Hypertension Alert: BP reading of {val_str} mmHg is elevated above normal (<120/80)."

        elif "glucose" in m or "sugar" in m:
            g = float(value)
            if g < 70:
                return f"🚨 Hypoglycemia Alert: Blood glucose of {g} mg/dL is dangerously low (<70 mg/dL). Consume fast-acting carbs."
            elif g > 200:
                return f"⚠️ Hyperglycemia Alert: Blood glucose of {g} mg/dL is significantly elevated."

        elif "sleep" in m:
            hrs = float(value)
            if hrs < 4.5:
                return f"⚠️ Sleep Deprivation Alert: Only {hrs} hours logged. Chronic low sleep impairs cognitive and cardiovascular recovery."

    except Exception:
        pass
    return None


def health_monitor(parameters: dict, player=None, **_context) -> str:
    """Log vitals, analyze trends, import wearable CSVs, and generate clinical summaries."""
    action = parameters.get("action", "summary").lower().strip()
    metric = parameters.get("metric", "heart_rate").strip()
    value = parameters.get("value")
    csv_path = parameters.get("csv_path", "").strip()
    notes = parameters.get("notes", "").strip()

    vitals_data = load_health_data("vitals_log.json", default={"records": []})
    records: List[Dict[str, Any]] = vitals_data.get("records", [])

    # ── Action: Log Single Metric ────────────────────────────────────────────
    if action in ("log", "record", "add"):
        if value is None:
            return "Sir, please provide the value for the biometric measurement." + MANDATORY_DISCLAIMER

        now_str = datetime.now().isoformat()
        anomaly_msg = _detect_vital_anomaly(metric, value)

        records.append({
            "timestamp": now_str,
            "metric": metric,
            "value": value,
            "notes": notes,
        })
        save_health_data("vitals_log.json", vitals_data)

        alert_line = f"\n\n{anomaly_msg}" if anomaly_msg else ""
        return (
            f"✅ Logged **{metric.replace('_', ' ').title()}**: {value} at {datetime.now().strftime('%H:%M')}.{alert_line}"
            + MANDATORY_DISCLAIMER
        )

    # ── Action: Import Wearable CSV ──────────────────────────────────────────
    elif action in ("import_csv", "import"):
        if not csv_path:
            return "Please provide the file path of the CSV export to ingest." + MANDATORY_DISCLAIMER
        path = Path(csv_path)
        if not path.exists():
            return f"CSV file not found at: {csv_path}" + MANDATORY_DISCLAIMER

        imported_count = 0
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Common wearable CSV header aliases
                    timestamp = row.get("date") or row.get("timestamp") or row.get("startDate") or datetime.now().isoformat()
                    val = row.get("value") or row.get("qty") or row.get("data")
                    m_type = row.get("type") or row.get("metric") or metric
                    if val:
                        records.append({
                            "timestamp": timestamp,
                            "metric": m_type,
                            "value": val,
                            "imported_from": path.name,
                        })
                        imported_count += 1
            save_health_data("vitals_log.json", vitals_data)
            return (
                f"✅ Successfully ingested {imported_count} telemetry records from {path.name} into encrypted health vault."
                + MANDATORY_DISCLAIMER
            )
        except Exception as e:
            return f"Failed to parse wearable CSV: {e}" + MANDATORY_DISCLAIMER

    # ── Action: Summary / Trend / Doctor Report ──────────────────────────────
    elif action in ("summary", "trend", "report", "doctor_summary"):
        if not records:
            return (
                "Sir, no biometric records have been logged yet. You can log vitals by saying: "
                "'log heart rate 72' or 'log blood pressure 120/80'."
                + MANDATORY_DISCLAIMER
            )

        # Aggregate by metric
        grouped: Dict[str, List[float]] = {}
        anomalies_detected = []

        for r in records:
            m = r["metric"].lower()
            val = r["value"]
            alert = _detect_vital_anomaly(m, val)
            if alert and alert not in anomalies_detected:
                anomalies_detected.append(alert)

            try:
                num = float(str(val).split("/")[0])  # Take systolic if BP
                grouped.setdefault(m, []).append(num)
            except Exception:
                pass

        summary_rows = []
        for m_name, vals in grouped.items():
            if vals:
                avg = sum(vals) / len(vals)
                min_v = min(vals)
                max_v = max(vals)
                summary_rows.append(
                    f"• **{m_name.replace('_', ' ').title()}**: Avg {avg:.1f} (Min: {min_v:.1f}, Max: {max_v:.1f}) across {len(vals)} readings"
                )

        anomaly_section = ""
        if anomalies_detected:
            anomaly_section = "\n\n### Clinical Alerts & Outliers Detected:\n" + "\n".join(anomalies_detected)

        return (
            f"📊 Patient Vitals Trend & Physician Summary ({len(records)} total records logged):\n\n"
            + "\n".join(summary_rows)
            + anomaly_section
            + "\n\nPrint or share this summary with your doctor at your upcoming appointment."
            + MANDATORY_DISCLAIMER
        )

    return (
        f"Unknown action '{action}'. Supported actions: log, summary, trend, import_csv."
        + MANDATORY_DISCLAIMER
    )


TOOL = {
    "name": "health_monitor",
    "description": (
        "ARC Biometric Health Monitor. Tracks time-series vitals (heart rate, blood pressure, "
        "sleep, glucose, steps), screens for hypertensive or glycemic anomalies, imports wearable CSVs, "
        "and prepares structured Doctor Appointment summaries."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'log', 'summary', 'trend', 'import_csv'",
            },
            "metric": {
                "type": "STRING",
                "description": "Biometric metric: 'heart_rate', 'blood_pressure', 'sleep_hours', 'blood_glucose', 'weight', 'steps'",
            },
            "value": {
                "type": "STRING",
                "description": "Measured value (e.g. '72', '125/82', '7.5', '110')",
            },
            "csv_path": {
                "type": "STRING",
                "description": "File path to wearable CSV export to import",
            },
            "notes": {
                "type": "STRING",
                "description": "Contextual notes (e.g. 'post-exercise', 'fasting')",
            },
        },
        "required": ["action"],
    },
    "handler": health_monitor,
}
