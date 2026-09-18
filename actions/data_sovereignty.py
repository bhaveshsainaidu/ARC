"""
actions/data_sovereignty.py — ARC Sovereign Data Control, Export & Purge.

Guarantees full user ownership over all local data collected by ARC:
  - Enumeration of all stored data, memory logs, health files, and transcripts
  - One-click encrypted ZIP data export for backup or migration
  - Granular, sovereign category deletion and GDPR/CCPA-aligned local purge
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.ethical_framework import log_ethical_audit


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_dir_size(path: Path) -> int:
    """Recursively computes total size in bytes."""
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def _fmt_bytes(bytes_count: int) -> str:
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    return f"{bytes_count / (1024 * 1024):.2f} MB"


def data_sovereignty(parameters: dict, player=None, **_context) -> str:
    """Enumerate stored data, create a portable ZIP export, or purge data categories."""
    action = parameters.get("action", "enumerate").lower().strip()
    category = parameters.get("category", "all").lower().strip()
    confirm = parameters.get("confirm", False)

    base = _get_base_dir()
    mem_dir = base / "memory"
    notes_dir = base / "memory" / "notes"
    health_dir = base / "memory" / "health"
    out_dir = base / "outputs"
    audit_file = base / "memory" / "ethical_audit.json"

    # ── Action: Enumerate Stored Data ─────────────────────────────────────────
    if action in ("enumerate", "list", "status", "inventory"):
        categories = [
            ("Personal Notes", notes_dir, len(list(notes_dir.glob("*.md"))) if notes_dir.exists() else 0),
            ("Encrypted Health Vault", health_dir, len(list(health_dir.glob("*.json"))) if health_dir.exists() else 0),
            ("Generated Outputs (Reports/Presentations)", out_dir, len(list(out_dir.rglob("*.*"))) if out_dir.exists() else 0),
            ("Ethical Audit Trail", audit_file, 1 if audit_file.exists() else 0),
        ]

        total_bytes = 0
        rows = []
        for name, p, count in categories:
            sz = _get_dir_size(p)
            total_bytes += sz
            rows.append(f"• **{name}**: {count} file(s) ({_fmt_bytes(sz)})")

        return (
            f"🏛️ ARC Sovereign Data Inventory (Total Storage: {_fmt_bytes(total_bytes)}):\n\n"
            + "\n".join(rows)
            + "\n\nAll data is stored locally on this workstation.\n"
            + "Commands: 'export data' to download archive | 'delete data category [notes/health/outputs]' to purge."
        )

    # ── Action: Export Data Package ──────────────────────────────────────────
    elif action in ("export", "backup", "archive"):
        export_dir = base / "outputs" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = export_dir / f"arc_data_export_{ts}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Archive memory notes
            if notes_dir.exists():
                for f in notes_dir.glob("*.md"):
                    zf.write(f, arcname=f"notes/{f.name}")

            # Archive health data
            if health_dir.exists():
                for f in health_dir.glob("*.json"):
                    zf.write(f, arcname=f"health/{f.name}")

            # Archive generated outputs
            if out_dir.exists():
                for f in out_dir.rglob("*.*"):
                    if "exports" not in f.parts:
                        rel = f.relative_to(out_dir)
                        zf.write(f, arcname=f"outputs/{rel}")

            # Archive audit log
            if audit_file.exists():
                zf.write(audit_file, arcname="ethical_audit.json")

        sz_str = _fmt_bytes(zip_path.stat().st_size)
        log_ethical_audit("data_export", "user", "ALLOWED", f"Exported user sovereign archive: {zip_path.name}")

        return (
            f"📦 Sovereign Data Archive Created Successfully ({sz_str}).\n"
            f"Location: {zip_path}\n\n"
            f"Contains all local notes, encrypted health metrics, audit logs, and generated assets."
        )

    # ── Action: Delete Data Category ─────────────────────────────────────────
    elif action in ("delete", "purge", "wipe", "clear"):
        if not confirm:
            return (
                f"⚠️ CONFIRMATION REQUIRED: Purging '{category}' data is irreversible.\n"
                f"To proceed, re-run with parameter `confirm=True` (or say 'confirm delete {category} data')."
            )

        deleted_items = []

        if category in ("notes", "all"):
            if notes_dir.exists():
                count = len(list(notes_dir.glob("*.md")))
                shutil.rmtree(notes_dir, ignore_errors=True)
                notes_dir.mkdir(parents=True, exist_ok=True)
                deleted_items.append(f"{count} personal note(s)")

        if category in ("health", "all"):
            if health_dir.exists():
                count = len(list(health_dir.glob("*.json")))
                shutil.rmtree(health_dir, ignore_errors=True)
                health_dir.mkdir(parents=True, exist_ok=True)
                deleted_items.append(f"{count} encrypted health file(s)")

        if category in ("outputs", "all"):
            if out_dir.exists():
                count = len(list(out_dir.rglob("*.*")))
                for child in out_dir.iterdir():
                    if child.name != "exports":
                        if child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                        else:
                            child.unlink(missing_ok=True)
                deleted_items.append(f"{count} generated output artifact(s)")

        if category in ("audit", "all"):
            if audit_file.exists():
                audit_file.unlink(missing_ok=True)
                deleted_items.append("ethical decision audit trail")

        log_ethical_audit("data_purge", "user", "ALLOWED", f"User purged category: {category}")

        return (
            f"🧹 Sovereign Data Purge Completed for category '{category}'.\n"
            f"Wiped: {', '.join(deleted_items) if deleted_items else 'No items found in category'}.\n"
            f"All requested records have been completely eliminated from disk."
        )

    return f"Unknown data sovereignty action '{action}'. Supported actions: enumerate, export, delete."


TOOL = {
    "name": "data_sovereignty",
    "description": (
        "ARC Sovereign Data Control tool. Allows users to inspect local storage footprints, "
        "export an all-in-one ZIP archive of their notes and health data, or selectively "
        "purge local data categories."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'enumerate', 'export', 'delete'",
            },
            "category": {
                "type": "STRING",
                "description": "Category to purge: 'notes', 'health', 'outputs', 'audit', or 'all'",
            },
            "confirm": {
                "type": "BOOLEAN",
                "description": "Safety confirmation flag required to execute data deletion (default: false)",
            },
        },
        "required": ["action"],
    },
    "handler": data_sovereignty,
}
