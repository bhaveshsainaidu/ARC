"""
scripts/create_shortcut.py — Create Windows Shortcuts for ARC.

Creates Desktop and Start Menu shortcuts pointing to the ARC launcher
with the custom icon and correct working directory.
Requires Windows 10/11. Zero external dependencies required (uses PowerShell WScript.Shell).
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.platform == "windows" or os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_DIR = Path(__file__).resolve().parent.parent
ICON_FILE = PROJECT_DIR / "config" / "jarvis.ico"
RUN_BAT = PROJECT_DIR / "run.bat"
MAIN_PY = PROJECT_DIR / "main.py"


def get_shortcut_targets() -> tuple[Path, Path]:
    """Get paths for Desktop and Start Menu shortcuts."""
    home = Path.home()
    desktop = home / "Desktop"
    start_menu = home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return desktop / "ARC.lnk", start_menu / "ARC.lnk"


def make_windows_shortcut(
    shortcut_path: Path,
    target_path: Path,
    arguments: str = "",
    working_dir: Path | None = None,
    icon_path: Path | None = None,
    description: str = "ARC Personal Voice Assistant",
) -> bool:
    """Create a Windows .lnk shortcut using PowerShell COM object."""
    if working_dir is None:
        working_dir = target_path.parent

    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{str(shortcut_path)}')
$Shortcut.TargetPath = '{str(target_path)}'
$Shortcut.Arguments = '{arguments}'
$Shortcut.WorkingDirectory = '{str(working_dir)}'
$Shortcut.Description = '{description}'
if ('{str(icon_path or "")}' -ne '' -and (Test-Path '{str(icon_path or "")}')) {{
    $Shortcut.IconLocation = '{str(icon_path)},0'
}}
$Shortcut.Save()
"""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=True,
        )
        return shortcut_path.exists()
    except Exception as e:
        print(f"Failed to create shortcut at {shortcut_path}: {e}")
        return False


def main():
    desktop_lnk, start_menu_lnk = get_shortcut_targets()

    if "--uninstall" in sys.argv or "--remove" in sys.argv:
        removed = 0
        for p in (desktop_lnk, start_menu_lnk):
            if p.exists():
                try:
                    p.unlink()
                    print(f"Removed shortcut: {p}")
                    removed += 1
                except Exception as e:
                    print(f"Failed to remove {p}: {e}")
        print(f"Uninstall complete: {removed} shortcut(s) removed.")
        return

    # Check launcher target:
    # If run.bat exists, use run.bat.
    # Otherwise, check for venv pythonw.exe or system pythonw.exe to launch without console window.
    target = RUN_BAT
    args = ""
    venv_pythonw = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
    sys_pythonw = Path(sys.executable).parent / "pythonw.exe"

    if RUN_BAT.exists():
        target = RUN_BAT
    elif venv_pythonw.exists():
        target = venv_pythonw
        args = f'"{MAIN_PY}"'
    elif sys_pythonw.exists():
        target = sys_pythonw
        args = f'"{MAIN_PY}"'
    else:
        target = Path(sys.executable)
        args = f'"{MAIN_PY}"'

    print("═══════════════════════════════════════════════════════════════")
    print("  ARC — SHORTCUT CREATION")
    print("═══════════════════════════════════════════════════════════════")
    print(f"Target      : {target}")
    print(f"Working Dir : {PROJECT_DIR}")
    print(f"Icon        : {ICON_FILE if ICON_FILE.exists() else 'Default'}")
    print("───────────────────────────────────────────────────────────────")

    created = 0
    if "--start-menu-only" not in sys.argv:
        if make_windows_shortcut(
            shortcut_path=desktop_lnk,
            target_path=target,
            arguments=args,
            working_dir=PROJECT_DIR,
            icon_path=ICON_FILE if ICON_FILE.exists() else None,
        ):
            print(f"[✔] Desktop shortcut created   : {desktop_lnk}")
            created += 1

    if "--desktop-only" not in sys.argv:
        if start_menu_lnk.parent.exists():
            if make_windows_shortcut(
                shortcut_path=start_menu_lnk,
                target_path=target,
                arguments=args,
                working_dir=PROJECT_DIR,
                icon_path=ICON_FILE if ICON_FILE.exists() else None,
            ):
                print(f"[✔] Start Menu shortcut created: {start_menu_lnk}")
                created += 1

    print("═══════════════════════════════════════════════════════════════")
    if created > 0:
        print(f"Successfully configured {created} shortcut(s) for ARC.")
    else:
        print("No shortcuts were created.")
    print("═══════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
