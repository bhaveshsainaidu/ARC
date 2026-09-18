"""
actions/quick_notes.py — Fast, Local Markdown Notes for ARC.

Provides instant voice-driven note taking, searching, listing, and reading.
Notes are stored locally in markdown format under memory/notes/.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def _get_notes_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    notes_dir = base / "memory" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    return notes_dir


def _clean_slug(title: str) -> str:
    s = re.sub(r"[^\w\s\-]", "", title).strip().lower()
    return re.sub(r"[-\s]+", "_", s)[:35] or "untitled"


def quick_notes(parameters: dict, player=None, **_context) -> str:
    """Manage local user notes."""
    action = parameters.get("action", "list").lower().strip()
    title = parameters.get("title", "").strip()
    content = parameters.get("content", "").strip()
    query = parameters.get("query", title).strip().lower()

    notes_dir = _get_notes_dir()

    # ── Action: Add Note ─────────────────────────────────────────────────────
    if action in ("add", "create", "save"):
        if not content and not title:
            return "Please provide a note title or content to save."
        if not title:
            title = content[:30] + ("..." if len(content) > 30 else "")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _clean_slug(title)
        filename = f"{timestamp}_{slug}.md"
        filepath = notes_dir / filename

        date_human = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_body = f"# {title}\nDate: {date_human}\n\n{content}\n"

        try:
            filepath.write_text(file_body, encoding="utf-8")
            return f"Note saved: '{title}' ({date_human})."
        except Exception as e:
            return f"Failed to save note: {e}"

    # ── Action: List Notes ───────────────────────────────────────────────────
    elif action in ("list", "all"):
        try:
            files = sorted(notes_dir.glob("*.md"), reverse=True)
            if not files:
                return "You have no saved notes yet. Say 'take a note' or 'add note' to create one."

            lines = [f"Stored Notes ({len(files)} total):"]
            for f in files[:8]:
                try:
                    text = f.read_text(encoding="utf-8")
                    first_line = text.split("\n", 1)[0].replace("#", "").strip()
                    lines.append(f"• {first_line} ({f.stem[:8]})")
                except Exception:
                    lines.append(f"• {f.stem}")
            if len(files) > 8:
                lines.append(f"... and {len(files) - 8} more.")
            return "\n".join(lines)
        except Exception as e:
            return f"Failed to list notes: {e}"

    # ── Action: Read Note ────────────────────────────────────────────────────
    elif action in ("read", "view", "get"):
        if not query and not title:
            return "Please specify which note you would like to read."

        target_query = (title or query).lower()
        try:
            files = list(notes_dir.glob("*.md"))
            for f in sorted(files, reverse=True):
                if target_query in f.name.lower():
                    return f"Note [{f.stem}]:\n\n" + f.read_text(encoding="utf-8")

            # Check inside content
            for f in sorted(files, reverse=True):
                txt = f.read_text(encoding="utf-8")
                if target_query in txt.lower():
                    return f"Note [{f.stem}]:\n\n" + txt

            return f"Could not find a note matching '{target_query}'."
        except Exception as e:
            return f"Error reading note: {e}"

    # ── Action: Search Notes ─────────────────────────────────────────────────
    elif action in ("search", "find"):
        if not query:
            return "Please specify what to search for in notes."

        matches = []
        try:
            for f in sorted(notes_dir.glob("*.md"), reverse=True):
                txt = f.read_text(encoding="utf-8")
                if query in txt.lower() or query in f.name.lower():
                    first_line = txt.split("\n", 1)[0].replace("#", "").strip()
                    matches.append(f"• {first_line} (in {f.name})")
                if len(matches) >= 5:
                    break

            if not matches:
                return f"No notes found mentioning '{query}'."
            return f"Notes matching '{query}':\n" + "\n".join(matches)
        except Exception as e:
            return f"Note search failed: {e}"

    # ── Action: Delete Note ──────────────────────────────────────────────────
    elif action in ("delete", "remove"):
        if not query and not title:
            return "Please specify which note to delete."
        target_query = (title or query).lower()
        try:
            for f in sorted(notes_dir.glob("*.md"), reverse=True):
                if target_query in f.name.lower() or target_query in f.read_text(encoding="utf-8")[:100].lower():
                    f.unlink()
                    return f"Deleted note: {f.stem}."
            return f"No note matched '{target_query}' to delete."
        except Exception as e:
            return f"Failed to delete note: {e}"

    else:
        return f"Unknown note action '{action}'. Supported actions: add, list, read, search, delete."


TOOL = {
    "name": "quick_notes",
    "description": (
        "Personal local markdown notes manager for ARC. "
        "Allows creating ('add'), listing ('list'), reading ('read'), searching ('search'), "
        "and deleting ('delete') quick notes saved on the laptop."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'add', 'list', 'read', 'search', 'delete'",
            },
            "title": {
                "type": "STRING",
                "description": "Title or subject of the note",
            },
            "content": {
                "type": "STRING",
                "description": "Content of the note (when creating)",
            },
            "query": {
                "type": "STRING",
                "description": "Search keyword or note title to read/delete",
            },
        },
        "required": ["action"],
    },
    "handler": quick_notes,
}
