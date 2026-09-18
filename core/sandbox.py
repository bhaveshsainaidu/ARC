"""
core/sandbox.py — Security Guardrails & Execution Sandbox for ARC.

Protects the host operating system from destructive commands, unauthorized system file
modifications, ransomware-like wipes, and privilege escalations.
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

# ── Protected System Directories (Disallow destructive writes/deletions) ──────
_PROTECTED_DIRS: set[Path] = set()

if _OS == "Windows":
    _sys_drive = os.environ.get("SystemDrive", "C:")
    _windir = os.environ.get("SystemRoot", f"{_sys_drive}\\Windows")
    _PROTECTED_DIRS.update([
        Path(_windir).resolve(),
        Path(f"{_windir}\\System32").resolve(),
        Path(f"{_windir}\\SysWOW64").resolve(),
        Path(f"{_sys_drive}\\Program Files").resolve(),
        Path(f"{_sys_drive}\\Program Files (x86)").resolve(),
        Path(f"{_sys_drive}\\ProgramData\\Microsoft").resolve(),
    ])
else:
    _PROTECTED_DIRS.update([
        Path("/bin").resolve(),
        Path("/sbin").resolve(),
        Path("/usr/bin").resolve(),
        Path("/usr/sbin").resolve(),
        Path("/etc").resolve(),
        Path("/boot").resolve(),
        Path("/sys").resolve(),
        Path("/dev").resolve(),
    ])

# ── Dangerous Command Regex Patterns ─────────────────────────────────────────
_DANGEROUS_PATTERNS = [
    # Recursive directory wipe
    r"\brmdir\s+/[sS]\b",
    r"\brd\s+/[sS]\b",
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f*|-r|-rf)\s+[/~]",
    r"\bdel\s+/[fF]\s+/[sS]\s+/[qQ]\b",
    r"\bdel\s+/[sS]\s+/[qQ]\b",
    # Disk formatting / partitioning
    r"\bformat\s+[a-zA-Z]:",
    r"\bdiskpart\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    # Registry destruction
    r"\breg\s+delete\s+[\"']?(HKLM|HKEY_LOCAL_MACHINE|HKCR|HKEY_CLASSES_ROOT)",
    # System takeover / permissions tamper
    r"\btakeown\s+/[fF]\s+[\"']?[cC]:\\windows",
    r"\bicacls\s+.*\/grant.*:F",
    # Malicious download & execute
    r"(?:iex|invoke-expression)\s*\(?\s*(?:new-object|curl|iwr|wget)",
    r"downloadstring\s*\(",
    r"\bcurl\b.*\|\s*(?:bash|sh|cmd|powershell)",
    r"\bwget\b.*\|\s*(?:bash|sh|cmd|powershell)",
    # Raw reverse shell patterns
    r"\bnc\s+.*-e\s+",
    r"/dev/tcp/\d+\.\d+\.\d+\.\d+",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERNS]


def validate_command_safety(command: str | list[str]) -> tuple[bool, str]:
    """Validate whether a command is safe to execute on the system.
    Returns (is_safe, reason)."""
    if isinstance(command, (list, tuple)):
        cmd_str = " ".join(str(c) for c in command)
    else:
        cmd_str = str(command)

    cmd_clean = cmd_str.strip()
    if not cmd_clean:
        return True, "Empty command."

    for pat in _COMPILED_PATTERNS:
        if pat.search(cmd_clean):
            return False, f"Dangerous command pattern blocked by Sandbox: '{pat.pattern}'"

    # Check for attempts to delete or alter protected OS paths
    lower_cmd = cmd_clean.lower()
    if any(k in lower_cmd for k in ("del ", "remove-item", "erase", "rm ", "unlink")):
        for protected in _PROTECTED_DIRS:
            prot_str = str(protected).lower()
            if prot_str in lower_cmd:
                return False, f"Operation targeting protected system directory blocked: {protected}"

    return True, "Command verified safe by Sandbox."


def is_safe_target_path(target: Path | str, allow_windows_read: bool = True) -> tuple[bool, str]:
    """Validate whether a path is safe for modification / deletion."""
    try:
        p = Path(target).expanduser().resolve()
    except Exception as e:
        return False, f"Invalid path syntax: {e}"

    for protected in _PROTECTED_DIRS:
        try:
            if p == protected or p.is_relative_to(protected):
                return False, f"Path is inside protected system location: {protected}"
        except Exception:
            pass

    return True, "Path is within safe user boundaries."


def run_sandboxed_command(
    command: str | list[str],
    timeout: int = 15,
    cwd: Path | None = None,
    allow_shell: bool = False,
) -> tuple[int, str, str]:
    """Execute a system command through the safety validator with timeout and caps."""
    safe, reason = validate_command_safety(command)
    if not safe:
        return -1, "", f"[Sandbox Security Alert] Execution Refused: {reason}"

    work_dir = cwd or Path.home()

    win_hide = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}

    try:
        proc = subprocess.run(
            command,
            shell=allow_shell,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            **win_hide,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -2, "", f"[Sandbox Timeout] Command exceeded maximum limit of {timeout}s."
    except Exception as e:
        return -3, "", f"[Sandbox Execution Error] {e}"
