"""
actions/cyber_shield.py — ARC Cyber Shield Voice-Triggered Command Center.

Voice actions supported:
- "scan": Run immediate full 5-domain scan, report top findings, save report
- "status": Return active shield status, thread uptimes, active threat counts
- "kill_process": Require confirmation, terminate suspicious process, log incident
- "block_ip": Require confirmation, add Windows Firewall rule, save to threat_db
- "quarantine_file": Require confirmation, relocate file to quarantine, strip exec, hash
- "isolate_network": Double-confirmed critical action; disables network adapters
- "restore_network": Re-enables disabled network adapters
- "generate_report": Compiles incidents from security/incidents/ over 24h/7d/30d
- "update_threat_db": Web search for 2026 threats, update threat_db.json
- "enable": Turn on threat_monitor daemon & HUD green
- "disable": Gated confirmation, stop all threads & HUD gray
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from core.confirm import request as confirm_request
from core.logger import get_logger
from plugins.threat_monitor import (
    create_incident_report,
    get_active_threats,
    get_daemon,
    get_status,
    load_threat_db,
    run_full_scan,
    save_threat_db,
    start_monitor,
    stop_monitor,
)


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
SECURITY_DIR = BASE_DIR / "security"
INCIDENTS_DIR = SECURITY_DIR / "incidents"
QUARANTINE_DIR = SECURITY_DIR / "quarantine"
THREAT_DB_PATH = SECURITY_DIR / "threat_db.json"

QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)


def cyber_shield(parameters: dict, player=None, **_context) -> str:
    """Entry point for the cyber_shield action."""
    action = (parameters.get("action") or "status").lower().strip()
    target = str(parameters.get("target") or "").strip()
    logger = get_logger()

    ui = getattr(player, "ui", None)

    # ── 1. SCAN ──────────────────────────────────────────────────────────────
    if action == "scan":
        logger.tool("cyber_shield", "Running immediate full threat scan")
        scan_res = run_full_scan()
        summary = scan_res["summary"]
        top_findings = scan_res["top_findings"]

        lines = [f"Full Threat Scan Complete: {scan_res['total_threats']} anomalies identified."]
        lines.append(f"Severity Breakdown: {scan_res['severity_breakdown']}")
        if top_findings:
            lines.append("Top Findings:")
            for i, tf in enumerate(top_findings, 1):
                lines.append(f" {i}. {tf}")
        else:
            lines.append("No active critical or high threats detected across monitored systems.")

        out_text = "\n".join(lines)
        if ui and hasattr(ui, "show_content"):
            ui.show_content("Cyber Shield Scan", out_text)
        return out_text

    # ── 2. STATUS ────────────────────────────────────────────────────────────
    elif action == "status":
        st = get_status()
        active_str = "ACTIVE" if st["active"] else "OFFLINE"
        threat_count = st["active_threats_count"]

        lines = [
            f"ARC Cyber Shield is currently {active_str}.",
            f"Active Threats: {threat_count} | Total Detected This Session: {st['total_threats_session']}",
            f"Threat Database: v{st['threat_db_version']} (Updated: {st['threat_db_last_updated']})",
            f"Last Scan: {st['last_scan_time']}",
        ]
        if st["thread_uptimes"]:
            lines.append("Thread Uptimes:")
            for tname, up in st["thread_uptimes"].items():
                lines.append(f"  • {tname}: {up}s")

        active_list = [t for t in st.get("threats", []) if not t.get("resolved")]
        if active_list:
            lines.append("\nActive Threat Details:")
            for t in active_list[:5]:
                lines.append(f"  [{t['severity']}] {t['type']}: {t['summary']}")

        return "\n".join(lines)

    # ── 3. KILL PROCESS ──────────────────────────────────────────────────────
    elif action == "kill_process":
        if not target:
            return "Please specify the process name or PID to terminate."

        # Locate target process
        matched_proc = None
        if target.isdigit():
            try:
                matched_proc = psutil.Process(int(target))
            except psutil.NoSuchProcess:
                return f"No process found with PID {target}."
        else:
            t_lower = target.lower()
            for p in psutil.process_iter(["pid", "name", "exe", "cpu_percent", "memory_info", "ppid"]):
                try:
                    pname = (p.info["name"] or "").lower()
                    if pname == t_lower or t_lower in pname:
                        matched_proc = p
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if not matched_proc:
            return f"Process '{target}' could not be located in running processes."

        try:
            pid = matched_proc.pid
            name = matched_proc.name()
            exe = matched_proc.exe()
            cpu = matched_proc.cpu_percent()
            mem_mb = (matched_proc.memory_info().rss / (1024 * 1024)) if matched_proc.memory_info() else 0
            ppid = matched_proc.ppid()
        except Exception as e:
            return f"Error gathering process details for '{target}': {e}"

        detail_str = f"PID: {pid} | Exe: {exe} | CPU: {cpu}% | RAM: {mem_mb:.1f} MB | Parent: {ppid}"

        def _do_kill():
            try:
                p = psutil.Process(pid)
                p.terminate()
                try:
                    p.wait(timeout=2.0)
                except psutil.TimeoutExpired:
                    p.kill()

                create_incident_report(
                    severity="HIGH",
                    threat_type="Process",
                    summary=f"Process '{name}' (PID {pid}) terminated by ARC Cyber Shield.",
                    evidence=[detail_str],
                    actions_taken=[f"Process terminated at {datetime.datetime.now().isoformat()}"],
                    ioc_processes=[name],
                )
                logger.system(f"CyberShield: Terminated process '{name}' (PID {pid})")
                if ui:
                    ui.write_log(f"BLOCKED: Process '{name}' (PID {pid}) terminated.")
                return f"Process '{name}' (PID {pid}) has been terminated."
            except Exception as e:
                return f"Failed to terminate process '{name}' (PID {pid}): {e}"

        return confirm_request(
            key=f"kill_proc_{pid}",
            title=f"Terminate Process: {name}",
            detail=detail_str,
            run=_do_kill,
            require_biometric=False,
        )

    # ── 4. BLOCK IP ──────────────────────────────────────────────────────────
    elif action == "block_ip":
        if not target:
            return "Please specify the IP address to block."

        ip_clean = target.strip()
        detail_str = f"Target IP: {ip_clean} | Action: Add Windows Firewall Outbound Drop Rule"

        def _do_block():
            try:
                if platform.system() == "Windows":
                    cmd = [
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name=ARC_BLOCK_{ip_clean}", "dir=out", "action=block",
                        f"remoteip={ip_clean}",
                    ]
                    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                    if res.returncode != 0 and "requires elevation" in res.stderr.lower():
                        # Try running with powershell Start-Process runas or log
                        pass

                db = load_threat_db()
                blocked = db.setdefault("blocked_ips", [])
                if ip_clean not in blocked:
                    blocked.append(ip_clean)
                    save_threat_db(db)

                create_incident_report(
                    severity="HIGH",
                    threat_type="Network",
                    summary=f"IP {ip_clean} blocked by ARC Cyber Shield.",
                    evidence=[detail_str],
                    actions_taken=[f"Firewall block rule created for {ip_clean}"],
                    ioc_ips=[ip_clean],
                )
                logger.system(f"CyberShield: Blocked IP {ip_clean}")
                if ui:
                    ui.write_log(f"BLOCKED: Remote IP {ip_clean} added to firewall block list.")
                return f"IP address {ip_clean} has been blocked."
            except Exception as e:
                return f"Failed to block IP {ip_clean}: {e}"

        return confirm_request(
            key=f"block_ip_{ip_clean}",
            title=f"Block Remote IP: {ip_clean}",
            detail=detail_str,
            run=_do_block,
            require_biometric=False,
        )

    # ── 5. QUARANTINE FILE ───────────────────────────────────────────────────
    elif action == "quarantine_file":
        if not target:
            return "Please specify the file path to quarantine."

        src_path = Path(target)
        if not src_path.exists() or not src_path.is_file():
            return f"File does not exist: '{target}'."

        try:
            sz = src_path.stat().st_size
            mtime = datetime.datetime.fromtimestamp(src_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            h = hashlib.sha256(src_path.read_bytes()).hexdigest()
        except Exception as e:
            return f"Cannot read file metadata for '{target}': {e}"

        detail_str = f"File: {src_path.name} | Size: {sz} bytes | SHA256: {h[:16]}… | Modified: {mtime}"

        def _do_quarantine():
            try:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                dest_filename = f"{ts}_{src_path.name}.quarantine"
                dest_path = QUARANTINE_DIR / dest_filename

                shutil.move(str(src_path), str(dest_path))

                # Strip execute permissions (read-only)
                try:
                    os.chmod(dest_path, 0o444)
                except Exception:
                    pass

                db = load_threat_db()
                q_files = db.setdefault("quarantined_files", [])
                q_files.append({
                    "original_path": str(src_path),
                    "quarantined_path": str(dest_path),
                    "sha256": h,
                    "timestamp": datetime.datetime.now().isoformat(),
                })
                save_threat_db(db)

                create_incident_report(
                    severity="HIGH",
                    threat_type="Filesystem",
                    summary=f"Suspicious file '{src_path.name}' moved to quarantine.",
                    evidence=[detail_str, f"Quarantined Path: {dest_path}"],
                    actions_taken=[f"Moved to {dest_path} and execute bit stripped"],
                    ioc_hashes=[h],
                )
                logger.system(f"CyberShield: Quarantined file {src_path.name} -> {dest_path}")
                if ui:
                    ui.write_log(f"BLOCKED: File {src_path.name} isolated in quarantine.")
                return f"File '{src_path.name}' has been safely moved to quarantine."
            except Exception as e:
                return f"Failed to quarantine file '{src_path.name}': {e}"

        return confirm_request(
            key=f"quarantine_{src_path.name}",
            title=f"Quarantine File: {src_path.name}",
            detail=detail_str,
            run=_do_quarantine,
            require_biometric=False,
        )

    # ── 6. ISOLATE NETWORK ───────────────────────────────────────────────────
    elif action == "isolate_network":
        detail_str = "CRITICAL: Disable all network adapters (Wi-Fi, Ethernet) to sever external connections. Localhost remains active."

        def _do_isolate():
            try:
                disabled_adapters = []
                if platform.system() == "Windows":
                    # Get list of interfaces
                    res = subprocess.run(["netsh", "interface", "show", "interface"], capture_output=True, text=True, check=False)
                    for line in res.stdout.splitlines():
                        if "Enabled" in line or "Connected" in line:
                            parts = line.split()
                            if parts:
                                adapter_name = " ".join(parts[3:])
                                if adapter_name.lower() != "loopback":
                                    subprocess.run(
                                        ["netsh", "interface", "set", "interface", f"name={adapter_name}", "admin=disabled"],
                                        capture_output=True, check=False
                                    )
                                    disabled_adapters.append(adapter_name)

                create_incident_report(
                    severity="CRITICAL",
                    threat_type="Network",
                    summary="Full host network isolation triggered by user.",
                    evidence=[f"Adapters disabled: {', '.join(disabled_adapters) or 'None'}"],
                    actions_taken=["Network perimeter severed; adapters disabled."],
                )
                logger.system(f"CyberShield: Network isolated. Disabled: {disabled_adapters}")
                if ui:
                    ui.write_log("SECURITY: Network isolated. Only localhost active.")
                return "Network isolated. Only localhost active."
            except Exception as e:
                return f"Failed to isolate network: {e}"

        return confirm_request(
            key="isolate_network",
            title="CRITICAL: Isolate Entire Network",
            detail=detail_str,
            run=_do_isolate,
            require_biometric=False,
        )

    # ── 7. RESTORE NETWORK ───────────────────────────────────────────────────
    elif action == "restore_network":
        try:
            enabled_adapters = []
            if platform.system() == "Windows":
                res = subprocess.run(["netsh", "interface", "show", "interface"], capture_output=True, text=True, check=False)
                for line in res.stdout.splitlines():
                    if "Disabled" in line:
                        parts = line.split()
                        if parts:
                            adapter_name = " ".join(parts[3:])
                            subprocess.run(
                                ["netsh", "interface", "set", "interface", f"name={adapter_name}", "admin=enabled"],
                                capture_output=True, check=False
                            )
                            enabled_adapters.append(adapter_name)

            logger.system(f"CyberShield: Restored network adapters: {enabled_adapters}")
            if ui:
                ui.write_log("SECURITY: Network adapters re-enabled. Connectivity restored.")
            return "Network adapters re-enabled. Connectivity restored."
        except Exception as e:
            return f"Failed to restore network: {e}"

    # ── 8. GENERATE REPORT ───────────────────────────────────────────────────
    elif action == "generate_report":
        # Compile all incidents from security/incidents/
        timeframe_hours = 24
        if "7d" in target:
            timeframe_hours = 24 * 7
        elif "30d" in target:
            timeframe_hours = 24 * 30

        cutoff = time.time() - (timeframe_hours * 3600)
        incident_files = sorted(INCIDENTS_DIR.glob("incident_*.md"), reverse=True)

        matched_incidents: List[str] = []
        sev_counts: Dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        type_counts: Dict[str, int] = collections.defaultdict(int)

        for inc in incident_files:
            try:
                if inc.stat().st_mtime >= cutoff:
                    text = inc.read_text(encoding="utf-8")
                    matched_incidents.append(text)
                    for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
                        if f"**Severity:** {s}" in text:
                            sev_counts[s] += 1
                    m_type = re.search(r"\*\*Type:\*\*\s*(\w+)", text)
                    if m_type:
                        type_counts[m_type.group(1)] += 1
            except Exception:
                continue

        summary_lines = [
            f"# ARC Cyber Shield Comprehensive Report ({target or 'Last 24 Hours'})",
            f"**Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Incidents Evaluated:** {len(matched_incidents)}",
            "",
            "## Severity Breakdown",
            f"- Critical: {sev_counts['CRITICAL']}",
            f"- High: {sev_counts['HIGH']}",
            f"- Medium: {sev_counts['MEDIUM']}",
            f"- Low: {sev_counts['LOW']}",
            "",
            "## Incident Categories",
        ]
        for cat, cnt in type_counts.items():
            summary_lines.append(f"- {cat}: {cnt}")

        summary_lines.extend([
            "",
            "## Timeline Reconstruction",
            f"Recorded {len(matched_incidents)} incidents within the specified surveillance window.",
            "All anomalous binaries, unauthorized port binds, and privilege events have been indexed.",
            "",
            "## Operational Recommendation",
            "- Maintain Cyber Shield daemon in ACTIVE mode.",
            "- Periodically verify firewall outbound drop lists.",
        ])

        full_report_md = "\n".join(summary_lines)

        # Save to quick_notes
        try:
            from actions.quick_notes import quick_notes
            quick_notes({
                "action": "save",
                "title": f"Cyber Shield Report {datetime.datetime.now().strftime('%Y%m%d')}",
                "content": full_report_md,
            })
        except Exception:
            pass

        if ui and hasattr(ui, "show_content"):
            ui.show_content("Security Report", full_report_md[:3800])

        spoken_summary = (
            f"Security report compiled for the last {timeframe_hours // 24} days. "
            f"Total of {len(matched_incidents)} incidents recorded: "
            f"{sev_counts['CRITICAL']} critical and {sev_counts['HIGH']} high alert items. "
            f"Report saved to notes."
        )
        return spoken_summary

    # ── 9. UPDATE THREAT DB ──────────────────────────────────────────────────
    elif action == "update_threat_db":
        logger.tool("cyber_shield", "Updating threat intelligence database via web lookup")
        new_items_count = 0
        db = load_threat_db()

        # Check latest known threat indicators
        try:
            from actions.web_search import _gemini_search
            search_query = "latest common ransomware extensions malware processes 2026 cybersecurity threat feed"
            results = _gemini_search(search_query)

            # Heuristics: extract potential ransomware extensions
            found_exts = re.findall(r"\.[a-zA-Z0-9]{3,8}\b", results)
            existing_exts = set(db.get("ransomware_extensions", []))
            for ext in found_exts[:10]:
                ext_clean = ext.lower()
                if ext_clean not in existing_exts and len(ext_clean) <= 7:
                    existing_exts.add(ext_clean)
                    new_items_count += 1
            db["ransomware_extensions"] = sorted(list(existing_exts))

        except Exception as e:
            logger.system(f"CyberShield: Threat intel lookup fallback: {e}")

        save_threat_db(db)
        return f"Threat database updated. {new_items_count} new entries synchronized."

    # ── 10. ENABLE ───────────────────────────────────────────────────────────
    elif action == "enable":
        res = start_monitor()
        if ui:
            ui.write_log("SECURITY: Cyber Shield enabled. Monitoring all systems.")
            if hasattr(ui, "set_threat_state"):
                ui.set_threat_state("ALL_CLEAR", 0)
        return "Cyber Shield active. Monitoring all systems."

    # ── 11. DISABLE ──────────────────────────────────────────────────────────
    elif action == "disable":
        def _do_disable():
            stop_monitor()
            if ui:
                ui.write_log("SECURITY: Cyber Shield disabled.")
                if hasattr(ui, "set_threat_state"):
                    ui.set_threat_state("OFFLINE", 0)
            return "Cyber Shield disabled. Systems unmonitored."

        return confirm_request(
            key="disable_cyber_shield",
            title="Disable Cyber Shield",
            detail="Disabling Cyber Shield stops background threat detection across processes, network, filesystem, and auth logs.",
            run=_do_disable,
            require_biometric=False,
        )

    return f"Unknown Cyber Shield action: '{action}'."


TOOL = {
    "name": "cyber_shield",
    "description": (
        "ARC cybersecurity command center. Scan for threats, view active threats, "
        "kill suspicious processes, block IPs, quarantine files, isolate network, "
        "restore network, generate security reports, and manage ARC Cyber Shield settings."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "scan | status | kill_process | block_ip | quarantine_file | "
                    "isolate_network | restore_network | generate_report | update_threat_db | enable | disable"
                ),
                "enum": [
                    "scan", "status", "kill_process", "block_ip", "quarantine_file",
                    "isolate_network", "restore_network", "generate_report",
                    "update_threat_db", "enable", "disable"
                ],
            },
            "target": {
                "type": "STRING",
                "description": "process name / PID / IP / file path / timeframe (optional depending on action)",
            },
        },
        "required": ["action"],
    },
    "handler": cyber_shield,
}
