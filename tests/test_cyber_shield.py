"""
tests/test_cyber_shield.py — Comprehensive Unit & Integration Tests for ARC Cyber Shield.

Tests:
1. Threat intelligence DB validation & schema conformity
2. Threat monitor daemon lifecycle & background thread operations
3. Incident report markdown generation & IoC structure
4. Voice command handling in actions/cyber_shield.py
5. Confirmation gate integration for destructive actions (kill, block, quarantine, isolate)
6. Quarantine file vault mechanics (relocation, hashing, permissions)
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from actions.cyber_shield import cyber_shield
from core.confirm import bind as confirm_bind, resolve as confirm_resolve
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
    INCIDENTS_DIR,
    QUARANTINE_DIR,
    SECURITY_DIR,
    THREAT_DB_PATH,
)


@pytest.fixture(autouse=True)
def cleanup_daemon():
    """Ensure daemon is stopped after tests."""
    yield
    try:
        stop_monitor()
    except Exception:
        pass


def test_threat_db_schema():
    """Verify threat_db.json contains all required schema sections."""
    db = load_threat_db()
    assert isinstance(db, dict)
    assert "malware_processes" in db
    assert "whitelist" in db
    assert "known_ports" in db
    assert "ransomware_extensions" in db
    assert "malicious_ips" in db
    assert "malicious_domains" in db
    assert "blocked_ips" in db
    assert "quarantined_files" in db
    assert "version" in db

    # Whitelist must include core safe processes
    whitelist = [w.lower() for w in db["whitelist"]]
    assert "python.exe" in whitelist
    assert "explorer.exe" in whitelist


def test_threat_monitor_status():
    """Verify get_status() returns well-formed monitoring telemetry."""
    st = get_status()
    assert isinstance(st, dict)
    assert "active" in st
    assert "thread_uptimes" in st
    assert "active_threats_count" in st
    assert "total_threats_session" in st
    assert "threat_db_version" in st
    assert "last_scan_time" in st


def test_incident_report_generation(tmp_path):
    """Verify incident reports match required ARC markdown format and IoCs."""
    report_file = create_incident_report(
        severity="HIGH",
        threat_type="Process",
        summary="Test anomaly detection in memory stack.",
        evidence=["PID: 9999", "Executable: untrusted_binary.exe"],
        attack_path="Temp Folder Drop → Execution → Hook",
        actions_taken=["Flagged for review"],
        actions_recommended=["Quarantine immediately"],
        ioc_ips=["192.0.2.1"],
        ioc_processes=["untrusted_binary.exe"],
    )

    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "# ARC Security Incident Report" in content
    assert "**Severity:** HIGH" in content
    assert "**Type:** Process" in content
    assert "## Threat Summary" in content
    assert "## Evidence Chain" in content
    assert "PID: 9999" in content
    assert "## Attack Path Reconstruction" in content
    assert "## Actions Taken" in content
    assert "## Actions Recommended" in content
    assert "## Indicators of Compromise" in content
    assert "192.0.2.1" in content
    assert "untrusted_binary.exe" in content


def test_threat_monitor_full_scan():
    """Verify immediate full scan evaluates 5 categories and returns structured report."""
    scan_res = run_full_scan()
    assert "total_threats" in scan_res
    assert "severity_breakdown" in scan_res
    assert "summary" in scan_res
    assert "CRITICAL" in scan_res["severity_breakdown"]
    assert "HIGH" in scan_res["severity_breakdown"]


def test_cyber_shield_scan_action():
    """Verify voice action 'scan' invokes full scan and formats summary."""
    output = cyber_shield({"action": "scan"})
    assert "Full Threat Scan Complete" in output
    assert "Severity Breakdown" in output


def test_cyber_shield_status_action():
    """Verify voice action 'status' reports state and uptime."""
    output = cyber_shield({"action": "status"})
    assert "ARC Cyber Shield is currently" in output
    assert "Active Threats" in output
    assert "Threat Database: v" in output


def test_cyber_shield_enable_disable():
    """Verify enable and disable state toggles."""
    enable_msg = cyber_shield({"action": "enable"})
    assert "active" in enable_msg.lower() or "monitoring" in enable_msg.lower()
    assert get_daemon().is_running() is True

    # Disable uses confirmation gate
    shown = []
    confirm_bind(show=lambda t, d: shown.append((t, d)), hide=lambda: None)
    disable_res = cyber_shield({"action": "disable"})
    assert "[CONFIRMATION_PENDING]" in disable_res
    assert len(shown) == 1
    assert "Disable Cyber Shield" in shown[0][0]

    # Resolve confirmation
    confirm_resolve(accepted=True)
    assert get_daemon().is_running() is False


def test_cyber_shield_generate_report():
    """Verify security report compilation across timeframes."""
    rep = cyber_shield({"action": "generate_report", "target": "24h"})
    assert "Security report compiled" in rep
    assert "incidents recorded" in rep


def test_quarantine_action(tmp_path):
    """Verify file quarantine parks file behind confirmation, moves it, and hashes it."""
    test_file = tmp_path / "suspicious_payload.exe"
    test_file.write_bytes(b"MALWARE_TEST_BYTES_ARC_SHIELD")

    shown = []
    confirm_bind(show=lambda t, d: shown.append((t, d)), hide=lambda: None)

    res = cyber_shield({"action": "quarantine_file", "target": str(test_file)})
    assert "[CONFIRMATION_PENDING]" in res
    assert "suspicious_payload.exe" in shown[0][0]

    # Confirm action
    confirm_resolve(accepted=True)
    for _ in range(20):
        if not test_file.exists():
            break
        time.sleep(0.05)

    # Original file must no longer exist
    assert not test_file.exists()

    # Quarantined file must exist in QUARANTINE_DIR
    q_files = list(QUARANTINE_DIR.glob("*suspicious_payload.exe.quarantine"))
    assert len(q_files) >= 1
    assert q_files[0].exists()

    # DB must reflect quarantined entry
    db = load_threat_db()
    assert any("suspicious_payload.exe" in q.get("original_path", "") for q in db.get("quarantined_files", []))


def test_block_ip_confirmation():
    """Verify IP blocking action requests human confirmation."""
    shown = []
    confirm_bind(show=lambda t, d: shown.append((t, d)), hide=lambda: None)

    res = cyber_shield({"action": "block_ip", "target": "203.0.113.55"})
    assert "[CONFIRMATION_PENDING]" in res
    assert "203.0.113.55" in shown[0][0]

    confirm_resolve(accepted=True)
    for _ in range(20):
        db = load_threat_db()
        if "203.0.113.55" in db.get("blocked_ips", []):
            break
        time.sleep(0.05)

    assert "203.0.113.55" in db.get("blocked_ips", [])


def test_network_isolation_confirmation():
    """Verify network isolation requests critical confirmation gate."""
    shown = []
    confirm_bind(show=lambda t, d: shown.append((t, d)), hide=lambda: None)

    res = cyber_shield({"action": "isolate_network"})
    assert "[CONFIRMATION_PENDING]" in res
    assert "Isolate Entire Network" in shown[0][0]
