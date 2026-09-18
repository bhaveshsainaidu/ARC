"""
actions/file_intelligence.py — Safe File Search, Duplicate Detection, and Cleanup Preview.

Enables ARC to find duplicate files, search safely across user folders,
and preview cleanups for Downloads/Desktop without performing destructive actions.
"""

from __future__ import annotations

import hashlib
import os
import platform
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

try:
    from core.confirm import request as confirm_request
except ImportError:
    confirm_request = None


def _hash_file(path: Path, max_kb: int = 1024) -> Optional[str]:
    """Fast SHA-256 hash of up to max_kb of a file for duplicate detection."""
    try:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            chunk = f.read(max_kb * 1024)
            hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def file_intelligence(parameters: dict, player=None, **_context) -> str:
    """Execute file intelligence tasks: search, duplicate scan, or cleanup preview."""
    task = parameters.get("task", "search").lower().strip()
    target_dir_str = parameters.get("directory", "").strip()
    query = parameters.get("query", "").strip().lower()
    ext = parameters.get("extension", "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext

    # Target directory resolution
    if not target_dir_str or target_dir_str in ("downloads", "download"):
        target_dir = Path.home() / "Downloads"
    elif target_dir_str in ("desktop",):
        target_dir = Path.home() / "Desktop"
    elif target_dir_str in ("documents", "docs"):
        target_dir = Path.home() / "Documents"
    else:
        try:
            target_dir = Path(target_dir_str).expanduser().resolve()
        except Exception:
            target_dir = Path.home() / "Downloads"

    if not target_dir.exists() or not target_dir.is_dir():
        return f"Directory does not exist or is not accessible: {target_dir}"

    # ── Task: Safe Search ────────────────────────────────────────────────────
    if task == "search":
        if not query and not ext:
            return "Please provide a query or extension to search for."

        matches = []
        try:
            for root, dirs, files in os.walk(target_dir):
                # Skip hidden / system directories
                dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d != "node_modules"]
                for f in files:
                    p = Path(root) / f
                    matches_query = query in f.lower() if query else True
                    matches_ext = p.suffix.lower() == ext if ext else True
                    if matches_query and matches_ext:
                        try:
                            stat = p.stat()
                            matches.append({
                                "name": f,
                                "path": str(p),
                                "size": _format_size(stat.st_size),
                                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                            })
                        except Exception:
                            continue
                    if len(matches) >= 20:
                        break
                if len(matches) >= 20:
                    break
        except Exception as e:
            return f"Search error in {target_dir}: {e}"

        if not matches:
            return f"No files found matching query '{query}' in {target_dir.name}."

        lines = [f"Found {len(matches)} matches in {target_dir.name}:"]
        for m in matches[:12]:
            lines.append(f"• {m['name']} ({m['size']}, {m['modified']})")
        if len(matches) > 12:
            lines.append(f"... and {len(matches) - 12} more files.")
        return "\n".join(lines)

    # ── Task: Find Duplicates ────────────────────────────────────────────────
    elif task in ("duplicates", "find_duplicates"):
        min_kb = int(parameters.get("min_size_kb", 100))
        size_map: dict[int, list[Path]] = {}
        scanned_count = 0

        try:
            for root, dirs, files in os.walk(target_dir):
                dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d != "node_modules"]
                for f in files:
                    p = Path(root) / f
                    try:
                        sz = p.stat().st_size
                        if sz >= min_kb * 1024:
                            size_map.setdefault(sz, []).append(p)
                            scanned_count += 1
                    except Exception:
                        continue
                    if scanned_count >= 500:
                        break
                if scanned_count >= 500:
                    break
        except Exception as e:
            return f"Scan failed: {e}"

        # Check candidate duplicate hashes
        dup_groups: list[dict[str, Any]] = []
        total_wasted_bytes = 0

        for sz, path_list in size_map.items():
            if len(path_list) < 2:
                continue
            hash_map: dict[str, list[Path]] = {}
            for p in path_list:
                h = _hash_file(p)
                if h:
                    hash_map.setdefault(h, []).append(p)
            for h, dups in hash_map.items():
                if len(dups) >= 2:
                    wasted = sz * (len(dups) - 1)
                    total_wasted_bytes += wasted
                    dup_groups.append({
                        "size": _format_size(sz),
                        "count": len(dups),
                        "files": [p.name for p in dups],
                    })

        if not dup_groups:
            return f"No duplicate files (>={min_kb} KB) found in {target_dir.name}."

        lines = [
            f"DUPLICATE FILE REPORT for {target_dir.name}:",
            f"Potential space savings: {_format_size(total_wasted_bytes)} across {len(dup_groups)} duplicate sets.",
            "Sample duplicates:",
        ]
        for g in dup_groups[:5]:
            lines.append(f"• {g['count']}x {g['files'][0]} ({g['size']} each)")
        lines.append("Note: No files were touched or deleted. Safe inspection complete.")
        return "\n".join(lines)

    # ── Task: Cleanup Preview ────────────────────────────────────────────────
    elif task in ("cleanup_preview", "cleanup"):
        days_old = int(parameters.get("days_old", 30))
        cutoff = datetime.now() - timedelta(days=days_old)

        categories = {
            "Installers": [".exe", ".msi", ".dmg", ".pkg"],
            "Archives":   [".zip", ".rar", ".7z", ".tar", ".gz"],
            "Documents":  [".pdf", ".docx", ".xlsx", ".pptx", ".txt"],
            "Media":      [".mp4", ".mov", ".mkv", ".mp3", ".wav", ".png", ".jpg", ".jpeg"],
        }
        category_counts: dict[str, int] = {k: 0 for k in categories}
        category_counts["Other"] = 0
        total_old_size = 0
        total_old_files = 0

        try:
            for p in target_dir.iterdir():
                if p.is_file() and not p.name.startswith("."):
                    stat = p.stat()
                    mtime = datetime.fromtimestamp(stat.st_mtime)
                    if mtime < cutoff:
                        total_old_files += 1
                        total_old_size += stat.st_size
                        matched = False
                        for cat, exts in categories.items():
                            if p.suffix.lower() in exts:
                                category_counts[cat] += 1
                                matched = True
                                break
                        if not matched:
                            category_counts["Other"] += 1
        except Exception as e:
            return f"Cleanup preview failed: {e}"

        if total_old_files == 0:
            return f"All files in {target_dir.name} are newer than {days_old} days. No cleanup needed."

        lines = [
            f"CLEANUP PREVIEW for {target_dir.name} (files older than {days_old} days):",
            f"Total old files: {total_old_files} ({_format_size(total_old_size)})",
            "Breakdown by category:",
        ]
        for cat, cnt in category_counts.items():
            if cnt > 0:
                lines.append(f"• {cat}: {cnt} file(s)")
        lines.append("\nThis is a non-destructive preview. Nothing has been moved or deleted.")
        return "\n".join(lines)

    else:
        return f"Unknown task: {task}. Supported tasks: 'search', 'duplicates', 'cleanup_preview'."


TOOL = {
    "name": "file_intelligence",
    "description": (
        "Safe file intelligence and storage optimization for Windows folders (Downloads, Desktop, etc.). "
        "Can perform safe search ('search'), find duplicate files with space savings report ('duplicates'), "
        "and generate non-destructive cleanup previews ('cleanup_preview') without deleting files."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task": {
                "type": "STRING",
                "description": "Task to perform: 'search', 'duplicates', or 'cleanup_preview'",
            },
            "directory": {
                "type": "STRING",
                "description": "Target folder (e.g. 'Downloads', 'Desktop', 'Documents', or full path)",
            },
            "query": {
                "type": "STRING",
                "description": "Search keyword or filename substring",
            },
            "extension": {
                "type": "STRING",
                "description": "File extension to filter (e.g. '.pdf', '.zip')",
            },
            "days_old": {
                "type": "INTEGER",
                "description": "Age threshold in days for cleanup preview (default: 30)",
            },
        },
        "required": ["task"],
    },
    "handler": file_intelligence,
}
