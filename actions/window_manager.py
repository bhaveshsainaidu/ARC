"""
actions/window_manager.py — Windows App & Window Control for ARC.

Allows the assistant to list visible windows, focus, minimize, maximize,
restore, close, snap windows to screen halves, and reliably search installed apps.
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

_IS_WINDOWS = platform.system() == "Windows"


def _list_visible_windows() -> list[dict[str, Any]]:
    """Return a list of visible application windows with titles and HWNDs."""
    if not _IS_WINDOWS:
        return []

    windows = []
    user32 = ctypes.windll.user32

    def enum_proc(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()
                # Exclude Windows background shells
                if title and title not in ("Default IME", "MSCTFIME UI", "Program Manager", "Settings"):
                    windows.append({"hwnd": hwnd, "title": title})
        return True

    ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    user32.EnumWindows(ENUM_WINDOWS_PROC(enum_proc), 0)
    return windows


def _find_window_by_query(query: str) -> Optional[dict[str, Any]]:
    """Find the best matching visible window by substring."""
    query_lower = query.lower().strip()
    windows = _list_visible_windows()
    # Exact match first
    for win in windows:
        if win["title"].lower() == query_lower:
            return win
    # Substring match
    for win in windows:
        if query_lower in win["title"].lower():
            return win
    return None


def _snap_window(hwnd: int, direction: str) -> bool:
    """Snap a window using SendInput or SetWindowPos."""
    if not _IS_WINDOWS:
        return False
    user32 = ctypes.windll.user32

    # First bring to focus
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)

    # Get monitor work area
    rect = ctypes.wintypes.RECT()
    user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    if direction == "left":
        user32.MoveWindow(hwnd, rect.left, rect.top, width // 2, height, True)
        return True
    elif direction == "right":
        user32.MoveWindow(hwnd, rect.left + (width // 2), rect.top, width // 2, height, True)
        return True
    elif direction == "top" or direction == "maximize":
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        return True
    return False


def _search_installed_apps(query: str) -> list[dict[str, str]]:
    """Search Windows Start Menu shortcuts and App Paths registry."""
    if not _IS_WINDOWS:
        return []

    results = []
    query_lower = query.lower().strip()
    seen = set()

    search_dirs = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]

    for root_dir in search_dirs:
        if not root_dir.exists():
            continue
        try:
            for p in root_dir.rglob("*.lnk"):
                name = p.stem
                if name.lower() not in seen and query_lower in name.lower():
                    seen.add(name.lower())
                    results.append({"name": name, "path": str(p)})
        except Exception:
            pass

    # Also search Registry App Paths
    try:
        import winreg
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            subkeys_count, _, _ = winreg.QueryInfoKey(key)
            for i in range(subkeys_count):
                subkey_name = winreg.EnumKey(key, i)
                if query_lower in subkey_name.lower():
                    clean_name = Path(subkey_name).stem
                    if clean_name.lower() not in seen:
                        seen.add(clean_name.lower())
                        results.append({"name": clean_name, "path": subkey_name})
    except Exception:
        pass

    return results


def window_manager(parameters: dict, player=None, **_context) -> str:
    """Handle window and application management requests."""
    action = parameters.get("action", "list").lower().strip()
    title = parameters.get("title", "").strip()
    query = parameters.get("query", title).strip()

    if not _IS_WINDOWS:
        return "Window management is currently supported on Windows."

    user32 = ctypes.windll.user32

    if action == "list":
        windows = _list_visible_windows()
        if not windows:
            return "No active visible application windows found."
        titles = [f"• {w['title']}" for w in windows[:15]]
        return f"Open Windows ({len(windows)} active):\n" + "\n".join(titles)

    if action == "search_app":
        if not query:
            return "Please provide an app name to search for."
        apps = _search_installed_apps(query)
        if not apps:
            return f"No installed application found matching '{query}'."
        lines = [f"• {a['name']}" for a in apps[:8]]
        return f"Found matching applications:\n" + "\n".join(lines)

    # Actions requiring a target window
    if not title and not query:
        return "Please specify the window title or application name."

    target = _find_window_by_query(title or query)
    if not target:
        return f"Could not find an active window matching '{title or query}'."

    hwnd = target["hwnd"]
    matched_title = target["title"]

    try:
        if action == "focus":
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return f"Focused window: {matched_title}"

        elif action == "minimize":
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return f"Minimized window: {matched_title}"

        elif action == "maximize":
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            return f"Maximized window: {matched_title}"

        elif action == "restore":
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            return f"Restored window: {matched_title}"

        elif action == "close":
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            return f"Closed window: {matched_title}"

        elif action in ("snap_left", "snap_right", "snap_top"):
            direction = action.replace("snap_", "")
            ok = _snap_window(hwnd, direction)
            if ok:
                return f"Snapped '{matched_title}' to the {direction}."
            return f"Failed to snap window '{matched_title}'."

        else:
            return f"Unknown window action: {action}. Use list, focus, minimize, maximize, restore, close, snap_left, snap_right, or search_app."
    except Exception as e:
        return f"Window operation failed: {e}"


TOOL = {
    "name": "window_manager",
    "description": (
        "Controls Windows application windows and searches installed programs. "
        "Can list open windows, focus, minimize, maximize, restore, close, "
        "or snap windows (snap_left, snap_right, snap_top), and search installed applications."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: 'list', 'focus', 'minimize', 'maximize', 'restore', 'close', 'snap_left', 'snap_right', 'snap_top', 'search_app'",
            },
            "title": {
                "type": "STRING",
                "description": "Window title or application name to match (for focus, minimize, snap, close, etc.)",
            },
            "query": {
                "type": "STRING",
                "description": "Application search query when action is 'search_app'",
            },
        },
        "required": ["action"],
    },
    "handler": window_manager,
}
