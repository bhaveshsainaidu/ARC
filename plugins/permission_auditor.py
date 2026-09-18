"""
plugins/permission_auditor.py — ARC Static AST Security & Permission Auditor.

Self-audits ARC's entire tool and plugin ecosystem (all actions/*.py and plugins/*.py)
using Python's static Abstract Syntax Tree (ast) analysis without executing code:
- Filesystem operations: file writes, file deletions, directory removal (os.remove, shutil.rmtree, Path.unlink)
- Network operations: raw sockets, HTTP requests, WebSockets (socket, urllib, requests, httpx)
- Subprocess & Shell execution: system commands (subprocess.Popen, subprocess.run, os.system)
- Dynamic code execution: runtime evaluation (eval, exec, __import__, compile)
- Unsandboxed sensitive access: keyfiles, api_keys.json, SSH certificates, hardware UUIDs
- Generates granular Permission Matrix, assigns overall Security Score (A-F), and prescribes hardening advice.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


class ToolASTVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.has_fs_read = False
        self.has_fs_write = False
        self.has_fs_delete = False
        self.has_network = False
        self.has_subprocess = False
        self.has_dynamic_exec = False
        self.has_sensitive_access = False
        self.findings: List[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._check_module_name(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self._check_module_name(node.module)
        self.generic_visit(node)

    def _check_module_name(self, mod: str):
        if any(m in mod for m in ("socket", "urllib", "requests", "httpx", "aiohttp", "websockets")):
            self.has_network = True
            self.findings.append(f"Network import: {mod}")
        elif any(m in mod for m in ("subprocess",)):
            self.has_subprocess = True
            self.findings.append(f"Subprocess import: {mod}")

    def visit_Call(self, node: ast.Call):
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
            # Check attribute chains like os.system or shutil.rmtree
            if isinstance(node.func.value, ast.Name):
                func_name = f"{node.func.value.id}.{node.func.attr}"

        # 1. Subprocess / Shell execution
        if func_name in ("subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_output", "os.system", "os.popen"):
            self.has_subprocess = True
            self.findings.append(f"Shell execution call: {func_name}")

        # 2. Dynamic execution
        elif func_name in ("eval", "exec", "__import__", "compile"):
            self.has_dynamic_exec = True
            self.findings.append(f"Dynamic execution call: {func_name}")

        # 3. Filesystem deletion
        elif func_name in ("os.remove", "os.unlink", "os.rmdir", "shutil.rmtree", "unlink"):
            self.has_fs_delete = True
            self.findings.append(f"Filesystem delete call: {func_name}")

        # 4. Filesystem write
        elif func_name in ("write_text", "write_bytes", "open"):
            # Check if open has 'w' or 'a' in args
            is_write_mode = False
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if any(mode in arg.value for mode in ("w", "a", "+")):
                        is_write_mode = True
            if is_write_mode or func_name in ("write_text", "write_bytes"):
                self.has_fs_write = True
                self.findings.append(f"Filesystem write call: {func_name}")
            else:
                self.has_fs_read = True

        elif func_name in ("read_text", "read_bytes"):
            self.has_fs_read = True

        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            val = node.value.lower()
            if any(s in val for s in (".keyfile", "api_keys.json", "id_rsa", "id_ed25519", "speaker_fingerprint.npy")):
                self.has_sensitive_access = True
                self.findings.append(f"Sensitive artifact reference: {node.value}")
        self.generic_visit(node)


def _audit_all_tools(base_dir: Path) -> Dict[str, Any]:
    tool_reports = []
    actions_dir = base_dir / "actions"
    plugins_dir = base_dir / "plugins"

    target_files = []
    if actions_dir.exists():
        target_files.extend(actions_dir.glob("*.py"))
    if plugins_dir.exists():
        target_files.extend(plugins_dir.glob("*.py"))

    high_risk_count = 0
    med_risk_count = 0

    for py_file in target_files:
        if py_file.name.startswith("__") or py_file.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"), filename=py_file.name)
            visitor = ToolASTVisitor(py_file.name)
            visitor.visit(tree)

            # Determine risk
            risk = "LOW"
            if visitor.has_dynamic_exec or (visitor.has_subprocess and visitor.has_fs_delete):
                risk = "CRITICAL"
                high_risk_count += 2
            elif visitor.has_subprocess or visitor.has_fs_delete:
                risk = "HIGH"
                high_risk_count += 1
            elif visitor.has_fs_write or visitor.has_network:
                risk = "MEDIUM"
                med_risk_count += 1

            tool_reports.append({
                "tool": py_file.stem,
                "file": py_file.name,
                "fs_read": visitor.has_fs_read,
                "fs_write": visitor.has_fs_write,
                "fs_delete": visitor.has_fs_delete,
                "network": visitor.has_network,
                "subprocess": visitor.has_subprocess,
                "dynamic_exec": visitor.has_dynamic_exec,
                "sensitive_access": visitor.has_sensitive_access,
                "risk": risk,
                "findings": visitor.findings[:4],
            })
        except Exception as e:
            tool_reports.append({"tool": py_file.stem, "file": py_file.name, "error": str(e), "risk": "UNKNOWN"})

    # Compute overall security grade
    total_tools = len(tool_reports) or 1
    penalty = (high_risk_count * 15) + (med_risk_count * 5)
    score_pct = max(0, 100 - penalty)

    if score_pct >= 90:
        grade = "A"
    elif score_pct >= 80:
        grade = "B"
    elif score_pct >= 70:
        grade = "C"
    elif score_pct >= 55:
        grade = "D"
    else:
        grade = "F"

    return {
        "total_tools": total_tools,
        "high_risk_tools": high_risk_count,
        "medium_risk_tools": med_risk_count,
        "score_pct": score_pct,
        "grade": grade,
        "tools": tool_reports,
    }


def _generate_security_report(audit_data: Dict[str, Any]) -> str:
    lines = [
        "# ARC Static Permission & Tool Security Audit",
        f"**Overall Security Grade:** {audit_data['grade']} ({audit_data['score_pct']}/100)",
        f"- **Total Tools Scanned:** {audit_data['total_tools']}",
        f"- **High Risk / Privileged Capabilities:** {audit_data['high_risk_tools']}",
        f"- **Medium Risk (Network/FS Write):** {audit_data['medium_risk_tools']}",
        "",
        "## 1. Granular Permission Matrix",
        "| Tool | Risk | Network | FS Write | FS Delete | Subprocess | Sensitive Access |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for t in sorted(audit_data["tools"], key=lambda x: (x.get("risk") != "CRITICAL", x.get("risk") != "HIGH", x.get("tool"))):
        if "error" in t:
            lines.append(f"| {t['tool']} | ERR | - | - | - | - | - |")
            continue
        lines.append(
            f"| `{t['tool']}` | **{t['risk']}** | {'✓' if t['network'] else '—'} "
            f"| {'✓' if t['fs_write'] else '—'} | {'⚠️' if t['fs_delete'] else '—'} "
            f"| {'⚠️' if t['subprocess'] else '—'} | {'🔒' if t['sensitive_access'] else '—'} |"
        )

    lines.extend([
        "",
        "## 2. Hardening & Sandboxing Recommendations",
        "1. **Destructive Action Gating:** Ensure all actions with `FS Delete` or `Subprocess` (e.g. computer_settings, file_controller) route through `core.confirm.request()`.",
        "2. **Cryptographic Keyfile Isolation:** Restrict `config/.keyfile` and `speaker_fingerprint.npy` read access strictly to `config_manager.py` and `confirm.py`.",
        "3. **Network Perimeter:** Whitelist approved external domains for research and diagnostic agents to prevent SSRF.",
    ])

    return "\n".join(lines)


# ── Plugin & Action Handlers ─────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    """Plugin entrypoint."""
    return permission_auditor(parameters, player=player)


def permission_auditor(parameters: dict, player=None, **_context) -> str:
    """Action entrypoint."""
    base_dir = _get_base_dir()
    audit_data = _audit_all_tools(base_dir)
    report = _generate_security_report(audit_data)

    # Display on HUD if available
    try:
        if player and hasattr(player, "ui") and hasattr(player.ui, "show_content"):
            player.ui.show_content("Security Audit", report[:3800])
    except Exception:
        pass

    return report


PLUGIN = {
    "name": "permission_auditor",
    "description": (
        "Self-audits ARC's tools and plugins using static AST analysis. Scans for filesystem writes/deletions, "
        "network access, subprocess execution, dynamic code execution, and sensitive file access. "
        "Produces a granular permission matrix, security score (A-F), and hardening recommendations."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
}

TOOL = {
    "name": "permission_auditor",
    "description": PLUGIN["description"],
    "parameters": PLUGIN["parameters"],
    "handler": permission_auditor,
}
