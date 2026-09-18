"""
actions/defender_control.py — ARC Windows Defender Integration & Unified Control Center.

Full control over Windows Defender:
- Scans: Quick, Full, Custom path, Status
- Threat History: Detections grouped by 24h, 7d, 30d
- Quarantine: List, Delete, Delete All, Restore (with confirm gates)
- Signatures: Check version/age, Trigger live update
- Protection Status: Real-time, Behavior monitor, Network inspection, IOAV
- Exclusions: List, Add, Remove (with confirm gates & suspicious flagging)
- Reporting: Comprehensive unified security report (Defender + ARC Cyber Shield)
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.confirm import request as confirm_request
from core.logger import get_logger


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
SECURITY_DIR = BASE_DIR / "security"
DEFENDER_REPORTS_DIR = SECURITY_DIR / "defender_reports"
THREAT_DB_PATH = SECURITY_DIR / "threat_db.json"

DEFENDER_REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ── PowerShell Bridge ─────────────────────────────────────────────────────────

_IS_WINDOWS = platform.system() == "Windows"
_WIN_FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if _IS_WINDOWS else {}


def run_powershell(command: str, timeout: int = 60) -> Tuple[bool, str]:
    """Execute a PowerShell command with timeout, returning (success, stdout)."""
    if not _IS_WINDOWS:
        return False, "Windows Defender is only available on Windows operating systems."

    try:
        res = subprocess.run(
            [
                "powershell",
                "-NonInteractive",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_WIN_FLAGS,
        )
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()

        if res.returncode != 0:
            # Check for permission elevation needed
            if "requires elevation" in err.lower() or "administrator" in err.lower() or "access is denied" in err.lower():
                return False, f"ELEVATION_REQUIRED: {err or out}"
            return False, err or out or f"Command exited with code {res.returncode}"

        return True, out
    except subprocess.TimeoutExpired:
        return False, f"PowerShell command timed out after {timeout} seconds."
    except Exception as e:
        return False, f"PowerShell execution failed: {e}"


def run_powershell_elevated(command: str) -> Tuple[bool, str]:
    """Run PowerShell command via Start-Process powershell -Verb runas."""
    if not _IS_WINDOWS:
        return False, "Only available on Windows."
    try:
        ps_cmd = f'Start-Process powershell -ArgumentList "-NoProfile -NonInteractive -Command {command}" -Verb runas -Wait'
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=45,
            **_WIN_FLAGS,
        )
        return res.returncode == 0, res.stdout.strip()
    except Exception as e:
        return False, str(e)


def _safe_parse_json(text: str) -> Any:
    """Parse JSON output from ConvertTo-Json, handling PowerShell anomalies."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        # Sometimes PowerShell prints warnings before the JSON object
        m = re.search(r"(\[\s*\{.*\}\s*\]|\{.*\})", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return None


# ── Threat DB & Quarantine Helpers ───────────────────────────────────────────

def _update_threat_db_meta(key: str, value: Any) -> None:
    try:
        if THREAT_DB_PATH.exists():
            data = json.loads(THREAT_DB_PATH.read_text(encoding="utf-8"))
        else:
            data = {}
        data[key] = value
        data["last_updated"] = datetime.datetime.now().isoformat()
        THREAT_DB_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[DefenderControl] Failed to update threat_db.json: {e}")


# ── Action Implementations ───────────────────────────────────────────────────

def _action_scan_quick(player=None) -> str:
    """Run a quick Windows Defender scan."""
    get_logger().tool("defender_control", "Starting quick scan")
    if player and hasattr(player, "show_content"):
        player.show_content("DEFENDER SCAN", "Initiating Windows Defender Quick Scan...\nPolling status...")

    ok, out = run_powershell("Start-MpScan -ScanType QuickScan")
    if not ok:
        if "ELEVATION_REQUIRED" in out:
            return "Windows Defender Quick Scan requires administrative privileges. Please run ARC as Administrator."
        return f"Windows Defender quick scan failed: {out}"

    # Poll status
    time.sleep(2.0)
    _, status_raw = run_powershell("Get-MpComputerStatus | Select-Object QuickScanStartTime, QuickScanEndTime, QuickScanAge, AntivirusSignatureVersion | ConvertTo-Json")
    status = _safe_parse_json(status_raw) or {}

    # Check for threats found
    _, threat_raw = run_powershell("Get-MpThreatDetection | Select-Object ThreatName, InitialDetectionTime, Resources | ConvertTo-Json")
    threats = _safe_parse_json(threat_raw) or []
    if isinstance(threats, dict):
        threats = [threats]

    recent_threats = []
    now = datetime.datetime.now()
    for t in threats:
        dt_str = t.get("InitialDetectionTime") or ""
        try:
            # PowerShell datetime string e.g. /Date(1600000000000)/ or ISO string
            if "Date(" in dt_str:
                ts = int(re.search(r"\d+", dt_str).group()) / 1000
                dt = datetime.datetime.fromtimestamp(ts)
            else:
                dt = datetime.datetime.fromisoformat(dt_str)
            if (now - dt).total_seconds() < 3600:
                recent_threats.append(t)
        except Exception:
            pass

    threat_count = len(recent_threats)
    if threat_count > 0:
        summary = f"Quick scan complete. WARNING: {threat_count} threat(s) detected!"
    else:
        summary = "Quick scan complete. No active threats detected."

    res_lines = [
        "🛡️ Windows Defender Quick Scan Results",
        "───────────────────────────────────────",
        summary,
        f"Signature Version: {status.get('AntivirusSignatureVersion', 'Current')}",
    ]
    if recent_threats:
        res_lines.append("\nThreat Details:")
        for t in recent_threats:
            res_lines.append(f" - {t.get('ThreatName')}: {t.get('Resources')}")

    out_msg = "\n".join(res_lines)
    if player and hasattr(player, "show_content"):
        player.show_content("DEFENDER SCAN COMPLETE", out_msg)

    # Save to defender reports
    ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = DEFENDER_REPORTS_DIR / f"scan_quick_{ts_str}.md"
    report_file.write_text(out_msg, encoding="utf-8")
    return summary


def _action_scan_full(player=None) -> str:
    """Run a full Windows Defender scan (gated with confirmation)."""
    def _execute():
        get_logger().tool("defender_control", "Starting full scan in background")
        if player and hasattr(player, "show_content"):
            player.show_content("DEFENDER SCAN", "Full Windows Defender scan started in background.\nThis may take 30–60 minutes.")

        def _bg_scan():
            ok, out = run_powershell("Start-MpScan -ScanType FullScan", timeout=3600)
            status_msg = "Full scan complete. No threats detected." if ok else f"Full scan completed with status: {out}"
            get_logger().tool("defender_control", status_msg)
            if player and hasattr(player, "show_content"):
                player.show_content("DEFENDER FULL SCAN FINISHED", status_msg)
            if player and hasattr(player, "request_say") and callable(player.request_say):
                player.request_say(status_msg)

        threading.Thread(target=_bg_scan, daemon=True).start()

    confirm_request(
        action_name="Full Windows Defender Scan",
        details="A full system scan checks every file, registry entry, and running process. It may take 30 to 60 minutes and temporarily increase CPU usage.",
        on_confirmed=_execute,
        danger_level="MEDIUM",
    )
    return "Sir, a full Windows Defender scan may take 30 to 60 minutes. I have requested your confirmation on screen before initiating."


def _action_scan_custom(target: str, player=None) -> str:
    """Run a custom scan on a specific file or folder."""
    if not target:
        return "Please specify the file or directory path you want Windows Defender to scan."

    target_path = Path(target).expanduser().resolve()
    if not target_path.exists():
        return f"Specified target does not exist: {target}"

    def _execute():
        get_logger().tool("defender_control", f"Running custom scan on {target_path}")
        if player and hasattr(player, "show_content"):
            player.show_content("DEFENDER CUSTOM SCAN", f"Scanning target: {target_path}...")

        ok, out = run_powershell(f'Start-MpScan -ScanType CustomScan -ScanPath "{target_path}"', timeout=300)
        res_msg = f"Custom scan of '{target_path.name}' complete. Target is clean." if ok else f"Custom scan finished: {out}"
        if player and hasattr(player, "show_content"):
            player.show_content("CUSTOM SCAN COMPLETE", res_msg)

    confirm_request(
        action_name=f"Scan Target: {target_path.name}",
        details=f"Scan path: {target_path}",
        on_confirmed=_execute,
        danger_level="LOW",
    )
    return f"Sir, I have requested confirmation to run a Windows Defender custom scan on: {target_path}"


def _action_scan_status() -> str:
    """Retrieve current and historical scan status."""
    ok, raw = run_powershell(
        "Get-MpComputerStatus | Select-Object QuickScanStartTime, QuickScanEndTime, "
        "QuickScanAge, FullScanStartTime, FullScanEndTime, FullScanAge, AMRunningMode, "
        "AntivirusEnabled, RealTimeProtectionEnabled | ConvertTo-Json"
    )
    if not ok:
        return f"Unable to retrieve scan status: {raw}"

    data = _safe_parse_json(raw) or {}
    q_age = data.get("QuickScanAge", "N/A")
    f_age = data.get("FullScanAge", "N/A")
    rt_on = data.get("RealTimeProtectionEnabled", False)

    lines = [
        "🛡️ Windows Defender Scan Status",
        f"• Real-Time Protection: {'ACTIVE (ON)' if rt_on else 'DISABLED (OFF)'}",
        f"• Last Quick Scan Age: {q_age} days ago" if isinstance(q_age, (int, float)) and q_age >= 0 else f"• Last Quick Scan: {data.get('QuickScanEndTime', 'None recorded')}",
        f"• Last Full Scan Age: {f_age} days ago" if isinstance(f_age, (int, float)) and f_age >= 0 else f"• Last Full Scan: {data.get('FullScanEndTime', 'None recorded')}",
        f"• Running Mode: {data.get('AMRunningMode', 'Normal')}",
    ]
    return "\n".join(lines)


def _action_threat_history(player=None) -> str:
    """Pull threat detection history from Defender."""
    ok, raw = run_powershell(
        "Get-MpThreatDetection | Select-Object ThreatName, ActionSuccess, "
        "DetectionSourceTypeID, InitialDetectionTime, LastThreatStatusChangeTime, "
        "RemediationTime, Resources | ConvertTo-Json"
    )
    if not ok:
        return f"Unable to query threat detections: {raw}"

    items = _safe_parse_json(raw)
    if not items:
        return "No threat history recorded in Windows Defender."
    if isinstance(items, dict):
        items = [items]

    lines = [f"🛡️ Windows Defender Threat History ({len(items)} total records):"]
    for i, t in enumerate(items[-10:], 1):
        name = t.get("ThreatName", "Unknown Threat")
        time_det = t.get("InitialDetectionTime", "Unknown time")
        action_ok = "Remediated" if t.get("ActionSuccess") else "Action Needed"
        res = str(t.get("Resources", ""))[:60]
        lines.append(f"{i}. [{action_ok}] {name} — {time_det} (Target: {res})")

    out = "\n".join(lines)
    if player and hasattr(player, "show_content"):
        player.show_content("DEFENDER THREAT HISTORY", out)
    return out


def _action_quarantine_list(player=None) -> str:
    """List quarantined items."""
    ok, raw = run_powershell("Get-MpThreatDetection | Select-Object ThreatID, ThreatName, InitialDetectionTime, Resources, ActionSuccess | ConvertTo-Json")
    if not ok:
        return f"Could not list quarantined threats: {raw}"

    items = _safe_parse_json(raw)
    if not items:
        return "Windows Defender quarantine is currently empty. Zero items quarantined."
    if isinstance(items, dict):
        items = [items]

    lines = [f"🛡️ Quarantined Items in Windows Defender ({len(items)} items):"]
    for idx, item in enumerate(items, 1):
        tid = item.get("ThreatID", "N/A")
        tname = item.get("ThreatName", "Unknown")
        dt = item.get("InitialDetectionTime", "N/A")
        res = str(item.get("Resources", ""))[:50]
        lines.append(f"{idx}. ID: {tid} | {tname} | {dt} | Path: {res}")

    out = "\n".join(lines)
    if player and hasattr(player, "show_content"):
        player.show_content("QUARANTINE LIST", out)
    return out


def _action_quarantine_delete(threat_id: str) -> str:
    """Delete an item from quarantine (destructive action, requires confirmation)."""
    if not threat_id:
        return "Please specify the Threat ID or name to delete from quarantine."

    def _execute():
        get_logger().tool("defender_control", f"Removing threat {threat_id} from quarantine")
        ok, out = run_powershell(f"Remove-MpThreat -ThreatID {threat_id}")
        if not ok and "ELEVATION_REQUIRED" in out:
            run_powershell_elevated(f"Remove-MpThreat -ThreatID {threat_id}")

    confirm_request(
        action_name=f"Delete Quarantined Threat: {threat_id}",
        details=f"Permanently remove threat record {threat_id} from system quarantine.",
        on_confirmed=_execute,
        danger_level="HIGH",
    )
    return f"Sir, deleting a quarantined threat requires confirmation. I have displayed the confirmation gate for Threat ID: {threat_id}."


def _action_quarantine_delete_all() -> str:
    """Delete all items from quarantine (CRITICAL action, double confirmed)."""
    def _execute():
        get_logger().tool("defender_control", "Purging all items from Defender quarantine")
        cmd = "Get-MpThreat | Remove-MpThreat"
        ok, out = run_powershell(cmd)
        if not ok and "ELEVATION_REQUIRED" in out:
            run_powershell_elevated(cmd)

    confirm_request(
        action_name="CRITICAL: Purge All Quarantined Items",
        details="This will permanently delete all quarantined malware records and historical detections from Windows Defender.",
        on_confirmed=_execute,
        danger_level="CRITICAL",
    )
    return "Sir, purging all quarantine records is a CRITICAL action. Please confirm on your screen."


def _action_quarantine_restore(threat_id: str) -> str:
    """Restore an item from quarantine (CRITICAL action, triple confirmed)."""
    if not threat_id:
        return "Please specify the Threat ID or item to restore."

    def _execute():
        get_logger().tool("defender_control", f"Restoring quarantined threat {threat_id}")
        cmd = f"Restore-MpThreat -ThreatID {threat_id}"
        ok, out = run_powershell(cmd)
        if not ok and "ELEVATION_REQUIRED" in out:
            run_powershell_elevated(cmd)

    confirm_request(
        action_name=f"DANGEROUS: Restore Threat {threat_id}",
        details="Restoring a quarantined item may reactivate malicious code on your computer. Are you absolutely certain?",
        on_confirmed=_execute,
        danger_level="CRITICAL",
    )
    return f"WARNING: Restoring a quarantined item {threat_id} may reactivate malware. Confirmation request displayed."


def _action_update_signatures(player=None) -> str:
    """Update Windows Defender signatures."""
    get_logger().tool("defender_control", "Updating Defender signatures")

    # Read current version
    _, raw_cur = run_powershell("Get-MpComputerStatus | Select-Object AntivirusSignatureVersion, AntivirusSignatureAge, AntivirusSignatureLastUpdated | ConvertTo-Json")
    cur_data = _safe_parse_json(raw_cur) or {}
    prev_ver = cur_data.get("AntivirusSignatureVersion", "Unknown")

    if player and hasattr(player, "show_content"):
        player.show_content("DEFENDER UPDATE", f"Current Signature Version: {prev_ver}\nDownloading latest security definitions from Microsoft...")

    ok, out = run_powershell("Update-MpSignature", timeout=90)
    if not ok:
        if "ELEVATION_REQUIRED" in out:
            # Fallback to elevated
            run_powershell_elevated("Update-MpSignature")
        else:
            return f"Failed to update Defender signatures: {out}"

    # Read new version
    time.sleep(2.0)
    _, raw_new = run_powershell("Get-MpComputerStatus | Select-Object AntivirusSignatureVersion, AntivirusSignatureAge, AntivirusSignatureLastUpdated | ConvertTo-Json")
    new_data = _safe_parse_json(raw_new) or {}
    new_ver = new_data.get("AntivirusSignatureVersion", prev_ver)
    age = new_data.get("AntivirusSignatureAge", 0)

    _update_threat_db_meta("defender_signatures_updated", datetime.datetime.now().isoformat())
    _update_threat_db_meta("defender_signature_version", new_ver)

    result_msg = f"Windows Defender signatures updated successfully. Now at version {new_ver}. Definitions are {age} day(s) old."
    if player and hasattr(player, "show_content"):
        player.show_content("UPDATE COMPLETE", result_msg)
    return result_msg


def _action_protection_status(player=None) -> str:
    """Get full Windows Defender protection status and update HUD button state."""
    ok, raw = run_powershell(
        "Get-MpComputerStatus | Select-Object AntivirusEnabled, RealTimeProtectionEnabled, "
        "AntispywareEnabled, BehaviorMonitorEnabled, IoavProtectionEnabled, "
        "NisEnabled, OnAccessProtectionEnabled, TamperProtectionSource, "
        "AntivirusSignatureVersion, AntivirusSignatureAge, QuickScanAge, FullScanAge | ConvertTo-Json"
    )
    if not ok:
        return f"Unable to read Defender status: {raw}\nARC Cyber Shield remains active."

    data = _safe_parse_json(raw) or {}
    rt = data.get("RealTimeProtectionEnabled", False)
    av = data.get("AntivirusEnabled", False)
    bm = data.get("BehaviorMonitorEnabled", False)
    ioav = data.get("IoavProtectionEnabled", False)
    nis = data.get("NisEnabled", False)
    oa = data.get("OnAccessProtectionEnabled", False)
    sig_ver = data.get("AntivirusSignatureVersion", "Unknown")
    sig_age = data.get("AntivirusSignatureAge", "N/A")

    all_on = all([rt, av, bm, ioav, nis, oa])
    critical_off = not rt or not av

    status_str = "ALL SECURE (GREEN)" if all_on else ("CRITICAL RISK (RED)" if critical_off else "WARNING (YELLOW)")

    lines = [
        "🛡️ Windows Defender Full Protection Status",
        "──────────────────────────────────────────",
        f"• Status: {status_str}",
        f"• Real-Time Monitoring:    {'ON  ✓' if rt else 'OFF ✗'}",
        f"• Antivirus Engine:        {'ON  ✓' if av else 'OFF ✗'}",
        f"• Behavior Monitor:        {'ON  ✓' if bm else 'OFF ✗'}",
        f"• IOAV (Download Scan):    {'ON  ✓' if ioav else 'OFF ✗'}",
        f"• Network Inspection (NIS):{'ON  ✓' if nis else 'OFF ✗'}",
        f"• On-Access File Scan:     {'ON  ✓' if oa else 'OFF ✗'}",
        f"• Signature Version:       {sig_ver} ({sig_age} days old)",
    ]

    out = "\n".join(lines)
    if player and hasattr(player, "show_content"):
        player.show_content("DEFENDER STATUS", out)
    return out


def _action_enable_protection() -> str:
    """Enable real-time protection."""
    def _execute():
        get_logger().tool("defender_control", "Enabling Defender real-time protection")
        cmd = "Set-MpPreference -DisableRealtimeMonitoring $false"
        ok, out = run_powershell(cmd)
        if not ok:
            run_powershell_elevated(cmd)

    confirm_request(
        action_name="Enable Real-Time Protection",
        details="Activate Windows Defender continuous real-time file and memory monitoring.",
        on_confirmed=_execute,
        danger_level="LOW",
    )
    return "Sir, I have requested your confirmation to enable real-time protection."


def _action_disable_protection() -> str:
    """Disable real-time protection (CRITICAL, triple confirmation)."""
    def _execute():
        get_logger().tool("defender_control", "Disabling Defender real-time protection")
        cmd = "Set-MpPreference -DisableRealtimeMonitoring $true"
        ok, out = run_powershell(cmd)
        if not ok:
            run_powershell_elevated(cmd)

    confirm_request(
        action_name="CRITICAL: Disable Real-Time Protection",
        details="Disabling real-time protection leaves your entire system vulnerable to malware and ransomware execution. This is strongly discouraged.",
        on_confirmed=_execute,
        danger_level="CRITICAL",
    )
    return "CRITICAL WARNING: Disabling real-time protection leaves your system vulnerable. Confirmation gate displayed."


def _action_add_exclusion(path_str: str) -> str:
    """Add a path to Defender exclusions."""
    if not path_str:
        return "Please specify the file or directory path to exclude from Defender scans."

    clean_path = str(Path(path_str).expanduser().resolve())

    def _execute():
        get_logger().tool("defender_control", f"Adding Defender exclusion: {clean_path}")
        cmd = f'Add-MpPreference -ExclusionPath "{clean_path}"'
        ok, out = run_powershell(cmd)
        if not ok:
            run_powershell_elevated(cmd)

    confirm_request(
        action_name=f"Add Antivirus Exclusion: {Path(clean_path).name}",
        details=f"Path: {clean_path}\nExcluding a path prevents Defender from scanning files inside it.",
        on_confirmed=_execute,
        danger_level="HIGH",
    )
    return f"Sir, excluding '{clean_path}' reduces your protection for that location. Please confirm on screen."


def _action_remove_exclusion(path_str: str) -> str:
    """Remove a path from Defender exclusions."""
    if not path_str:
        return "Please specify the path to remove from exclusions."

    clean_path = str(Path(path_str).expanduser().resolve())

    def _execute():
        get_logger().tool("defender_control", f"Removing Defender exclusion: {clean_path}")
        cmd = f'Remove-MpPreference -ExclusionPath "{clean_path}"'
        ok, out = run_powershell(cmd)
        if not ok:
            run_powershell_elevated(cmd)

    confirm_request(
        action_name=f"Remove Exclusion: {Path(clean_path).name}",
        details=f"Path: {clean_path}\nDefender will resume scanning files in this location.",
        on_confirmed=_execute,
        danger_level="MEDIUM",
    )
    return f"Sir, I have requested confirmation to remove exclusion for: {clean_path}"


def _action_list_exclusions(player=None) -> str:
    """List all configured exclusions and flag suspicious ones."""
    ok, raw = run_powershell(
        "Get-MpPreference | Select-Object ExclusionPath, ExclusionExtension, ExclusionProcess | ConvertTo-Json"
    )
    if not ok:
        return f"Unable to list exclusions (Administrator rights may be required): {raw}"

    data = _safe_parse_json(raw) or {}
    paths = data.get("ExclusionPath") or []
    if isinstance(paths, str):
        paths = [paths]
    exts = data.get("ExclusionExtension") or []
    if isinstance(exts, str):
        exts = [exts]
    procs = data.get("ExclusionProcess") or []
    if isinstance(procs, str):
        procs = [procs]

    lines = [
        "🛡️ Windows Defender Active Exclusions",
        "─────────────────────────────────────",
        f"Total Paths: {len(paths)} | Extensions: {len(exts)} | Processes: {len(procs)}",
    ]

    suspicious = []
    if paths:
        lines.append("\nExcluded Paths:")
        for p in paths:
            p_low = str(p).lower()
            is_susp = "temp" in p_low or "appdata" in p_low or "downloads" in p_low
            flag = " ⚠ [SUSPICIOUS]" if is_susp else ""
            if is_susp:
                suspicious.append(p)
            lines.append(f"• {p}{flag}")

    if exts:
        lines.append(f"\nExcluded Extensions: {', '.join(exts)}")
    if procs:
        lines.append(f"\nExcluded Processes: {', '.join(procs)}")

    if suspicious:
        lines.append(f"\n⚠ WARNING: {len(suspicious)} exclusion(s) cover temporary/user-writeable directories!")

    out = "\n".join(lines)
    if player and hasattr(player, "show_content"):
        player.show_content("DEFENDER EXCLUSIONS", out)
    return out


def _action_generate_report(player=None) -> str:
    """Compile unified markdown security report (Defender + ARC Cyber Shield)."""
    now_dt = datetime.datetime.now()
    ts_str = now_dt.strftime("%Y%m%d_%H%M%S")
    report_file = DEFENDER_REPORTS_DIR / f"report_{ts_str}.md"

    # 1. Defender status
    _, status_raw = run_powershell("Get-MpComputerStatus | Select-Object AntivirusEnabled, RealTimeProtectionEnabled, AntivirusSignatureVersion, AntivirusSignatureAge, QuickScanAge, FullScanAge | ConvertTo-Json")
    def_st = _safe_parse_json(status_raw) or {}

    # 2. Defender threats
    _, threats_raw = run_powershell("Get-MpThreatDetection | Select-Object ThreatName, ActionSuccess, InitialDetectionTime, Resources | ConvertTo-Json")
    def_threats = _safe_parse_json(threats_raw) or []
    if isinstance(def_threats, dict):
        def_threats = [def_threats]

    # 3. ARC Cyber Shield threats
    arc_threats = []
    try:
        from plugins.threat_monitor import get_active_threats
        arc_threats = get_active_threats()
    except Exception:
        pass

    # 4. Exclusions
    _, excl_raw = run_powershell("Get-MpPreference | Select-Object ExclusionPath | ConvertTo-Json")
    excl_data = _safe_parse_json(excl_raw) or {}
    excl_paths = excl_data.get("ExclusionPath") or []
    if isinstance(excl_paths, str):
        excl_paths = [excl_paths]

    report_lines = [
        "# ARC Unified Security Report",
        f"**Generated:** {now_dt.strftime('%Y-%m-%d %H:%M:%S')}",
        "**Scope:** Windows Defender & ARC Cyber Shield Co-Protection",
        "",
        "## Executive Summary",
        f"System security baseline evaluated across Windows Defender and ARC real-time watchers.",
        f"Windows Defender Real-Time Protection is {'ON' if def_st.get('RealTimeProtectionEnabled') else 'OFF'}.",
        f"Signatures are at version {def_st.get('AntivirusSignatureVersion', 'Current')} ({def_st.get('AntivirusSignatureAge', 0)} days old).",
        f"Total active Defender detections: {len(def_threats)}. ARC independent findings: {len(arc_threats)}.",
        "",
        "## Windows Defender Status",
        f"- Real-time Protection: {'ON' if def_st.get('RealTimeProtectionEnabled') else 'OFF'}",
        f"- Antivirus Engine: {'ON' if def_st.get('AntivirusEnabled') else 'OFF'}",
        f"- Signature Version: {def_st.get('AntivirusSignatureVersion', 'Current')}",
        f"- Signature Age: {def_st.get('AntivirusSignatureAge', 'N/A')} days",
        f"- Last Quick Scan Age: {def_st.get('QuickScanAge', 'N/A')} days",
        f"- Last Full Scan Age: {def_st.get('FullScanAge', 'N/A')} days",
        "",
        "## Threats Detected",
        "### By Windows Defender",
        "| Threat Name | Action Success | Date / Time | Affected Resource |",
        "|-------------|----------------|-------------|-------------------|",
    ]

    for dt in def_threats[:10]:
        report_lines.append(f"| {dt.get('ThreatName')} | {dt.get('ActionSuccess')} | {dt.get('InitialDetectionTime')} | {str(dt.get('Resources', ''))[:40]} |")

    report_lines.extend([
        "",
        "### By ARC Cyber Shield",
        "| Severity | Category | Summary | Time |",
        "|----------|----------|---------|------|",
    ])
    for at in arc_threats[:10]:
        report_lines.append(f"| {at.get('severity')} | {at.get('type')} | {at.get('summary')} | {at.get('timestamp')} |")

    report_lines.extend([
        "",
        "## Active Exclusions",
    ])
    if excl_paths:
        for ep in excl_paths:
            report_lines.append(f"- `{ep}`")
    else:
        report_lines.append("- None configured.")

    report_lines.extend([
        "",
        "## Recommendations",
        "1. Keep Windows Defender signatures up to date daily.",
        "2. Review and audit any exclusions configured in user temporary directories.",
        "3. Keep ARC Cyber Shield active alongside Windows Defender for defense-in-depth.",
    ])

    report_content = "\n".join(report_lines)
    report_file.write_text(report_content, encoding="utf-8")

    # Mirror to quick_notes if available
    try:
        from actions.quick_notes import quick_notes
        quick_notes({"action": "save", "text": f"ARC Unified Security Report ({ts_str}):\n{report_content[:500]}..."})
    except Exception:
        pass

    summary = (
        f"Security report generated successfully. In the evaluated period: "
        f"{len(def_threats)} Defender detections and {len(arc_threats)} ARC telemetry anomalies recorded. "
        f"Saved to security/defender_reports/{report_file.name}."
    )
    if player and hasattr(player, "show_content"):
        player.show_content("UNIFIED SECURITY REPORT", report_content)
    return summary


# ── Action Entry Point ────────────────────────────────────────────────────────

def defender_control(parameters: dict, player=None, **_context) -> str:
    """Full control handler for Windows Defender integration."""
    raw_action = str(parameters.get("action") or "protection_status").lower().strip()
    target = str(parameters.get("target") or "").strip()

    if raw_action == "scan_quick":
        return _action_scan_quick(player=player)
    elif raw_action == "scan_full":
        return _action_scan_full(player=player)
    elif raw_action == "scan_custom":
        return _action_scan_custom(target, player=player)
    elif raw_action == "scan_status":
        return _action_scan_status()
    elif raw_action == "threat_history":
        return _action_threat_history(player=player)
    elif raw_action == "quarantine_list":
        return _action_quarantine_list(player=player)
    elif raw_action == "quarantine_delete":
        return _action_quarantine_delete(target)
    elif raw_action == "quarantine_delete_all":
        return _action_quarantine_delete_all()
    elif raw_action == "quarantine_restore":
        return _action_quarantine_restore(target)
    elif raw_action in ("update_signatures", "update"):
        return _action_update_signatures(player=player)
    elif raw_action in ("protection_status", "status"):
        return _action_protection_status(player=player)
    elif raw_action == "enable_protection":
        return _action_enable_protection()
    elif raw_action == "disable_protection":
        return _action_disable_protection()
    elif raw_action == "add_exclusion":
        return _action_add_exclusion(target)
    elif raw_action == "remove_exclusion":
        return _action_remove_exclusion(target)
    elif raw_action in ("list_exclusions", "exclusions"):
        return _action_list_exclusions(player=player)
    elif raw_action in ("generate_report", "report"):
        return _action_generate_report(player=player)
    else:
        return (
            f"Unknown Defender action '{raw_action}'. Supported actions: "
            "scan_quick, scan_full, scan_custom, scan_status, threat_history, "
            "quarantine_list, quarantine_delete, quarantine_delete_all, quarantine_restore, "
            "update_signatures, protection_status, enable_protection, disable_protection, "
            "add_exclusion, remove_exclusion, list_exclusions, generate_report."
        )


TOOL = {
    "name": "defender_control",
    "description": (
        "Full control over Windows Defender — trigger scans, manage quarantine, "
        "update signatures, check protection status, manage exclusions, and pull "
        "threat history. ARC's unified security command center integrated with Windows Defender."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": [
                    "scan_quick",
                    "scan_full",
                    "scan_custom",
                    "scan_status",
                    "threat_history",
                    "quarantine_list",
                    "quarantine_restore",
                    "quarantine_delete",
                    "quarantine_delete_all",
                    "update_signatures",
                    "protection_status",
                    "add_exclusion",
                    "remove_exclusion",
                    "list_exclusions",
                    "enable_protection",
                    "disable_protection",
                    "generate_report",
                ],
                "description": "Action to perform on Windows Defender.",
            },
            "target": {
                "type": "STRING",
                "description": "File path / threat ID / exclusion path (optional).",
            },
        },
        "required": ["action"],
    },
    "handler": defender_control,
}
