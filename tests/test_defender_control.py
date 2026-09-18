"""
tests/test_defender_control.py — Unit tests for Windows Defender integration in ARC.

Verifies:
- actions/defender_control.py: Tool definition, actions, confirmation gates, reporting
- plugins/defender_monitor.py: Plugin definition, start/stop, status, event correlation
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from actions.defender_control import TOOL as DEFENDER_TOOL, defender_control, run_powershell
from plugins.defender_monitor import PLUGIN as DEFENDER_PLUGIN, DefenderMonitorDaemon, get_defender_daemon, _correlate_threat


class TestDefenderControl(unittest.TestCase):

    def test_tool_declaration(self):
        """Verify defender_control TOOL conforms to schema."""
        self.assertEqual(DEFENDER_TOOL["name"], "defender_control")
        self.assertIn("action", DEFENDER_TOOL["parameters"]["properties"])
        self.assertTrue(callable(DEFENDER_TOOL["handler"]))

    def test_plugin_declaration(self):
        """Verify defender_monitor PLUGIN conforms to schema."""
        self.assertEqual(DEFENDER_PLUGIN["name"], "defender_monitor")
        self.assertIn("action", DEFENDER_PLUGIN["parameters"]["properties"])

    def test_protection_status(self):
        """Verify protection_status queries computer status and returns summary."""
        mock_json = json.dumps({
            "AntivirusEnabled": True,
            "RealTimeProtectionEnabled": True,
            "AntispywareEnabled": True,
            "BehaviorMonitorEnabled": True,
            "IoavProtectionEnabled": True,
            "NisEnabled": True,
            "OnAccessProtectionEnabled": True,
            "AntivirusSignatureVersion": "1.405.120.0",
            "AntivirusSignatureAge": 0,
        })
        with patch("actions.defender_control.run_powershell", return_value=(True, mock_json)):
            res = defender_control({"action": "protection_status"})
            self.assertIn("Windows Defender Full Protection Status", res)
            self.assertIn("Real-Time Monitoring", res)
            self.assertIn("ON  ✓", res)

    def test_scan_status(self):
        """Verify scan_status returns formatted scan ages and states."""
        mock_json = json.dumps({
            "QuickScanAge": 1,
            "FullScanAge": 5,
            "AMRunningMode": "Normal",
            "RealTimeProtectionEnabled": True,
        })
        with patch("actions.defender_control.run_powershell", return_value=(True, mock_json)):
            res = defender_control({"action": "scan_status"})
            self.assertIn("Windows Defender Scan Status", res)
            self.assertIn("Last Quick Scan Age: 1 days ago", res)

    def test_threat_history_empty(self):
        """Verify threat_history handles empty detections gracefully."""
        with patch("actions.defender_control.run_powershell", return_value=(True, "")):
            res = defender_control({"action": "threat_history"})
            self.assertIn("No threat history recorded", res)

    def test_quarantine_list_empty(self):
        """Verify quarantine_list returns empty notice when no threats."""
        with patch("actions.defender_control.run_powershell", return_value=(True, "")):
            res = defender_control({"action": "quarantine_list"})
            self.assertIn("zero items quarantined", res.lower())

    def test_quarantine_delete_requires_confirmation(self):
        """Verify delete action gates through confirm.py."""
        with patch("actions.defender_control.confirm_request") as mock_confirm:
            res = defender_control({"action": "quarantine_delete", "target": "12345"})
            self.assertTrue(mock_confirm.called)
            self.assertIn("12345", res)

    def test_scan_full_requires_confirmation(self):
        """Verify full scan gates through confirm.py."""
        with patch("actions.defender_control.confirm_request") as mock_confirm:
            res = defender_control({"action": "scan_full"})
            self.assertTrue(mock_confirm.called)
            self.assertIn("30 to 60 minutes", res)

    def test_update_signatures(self):
        """Verify signature update queries and returns version info."""
        mock_json_cur = json.dumps({"AntivirusSignatureVersion": "1.400.0.0", "AntivirusSignatureAge": 2})
        mock_json_new = json.dumps({"AntivirusSignatureVersion": "1.401.0.0", "AntivirusSignatureAge": 0})
        with patch("actions.defender_control.run_powershell", side_effect=[
            (True, mock_json_cur),
            (True, ""),
            (True, mock_json_new)
        ]):
            res = defender_control({"action": "update_signatures"})
            self.assertIn("updated successfully", res)
            self.assertIn("1.401.0.0", res)

    def test_generate_report(self):
        """Verify unified report generation compiles markdown file."""
        with TemporaryDirectory() as tmp_dir:
            tmp_reports = Path(tmp_dir)
            with patch("actions.defender_control.DEFENDER_REPORTS_DIR", tmp_reports), \
                 patch("actions.defender_control.run_powershell", return_value=(True, "{}")):
                res = defender_control({"action": "generate_report"})
                self.assertIn("Security report generated successfully", res)
                files = list(tmp_reports.glob("report_*.md"))
                self.assertEqual(len(files), 1)
                content = files[0].read_text(encoding="utf-8")
                self.assertIn("# ARC Unified Security Report", content)

    def test_defender_monitor_lifecycle(self):
        """Verify defender_monitor start, stop, and status APIs."""
        daemon = DefenderMonitorDaemon.get_instance()
        status_before = daemon.get_status()
        self.assertIn("active", status_before)

        # Start and stop
        daemon.start()
        self.assertTrue(daemon.is_running())
        daemon.stop()
        self.assertFalse(daemon.is_running())

    def test_threat_correlation(self):
        """Verify correlation matches when resource or name overlaps with ARC threats."""
        mock_threats = [
            {
                "summary": "Suspicious backdoor in C:/test/malware.exe",
                "evidence": ["Path: C:/test/malware.exe"],
            }
        ]
        with patch("plugins.threat_monitor.get_active_threats", return_value=mock_threats):
            correlated = _correlate_threat("Trojan.Win32", "C:/test/malware.exe")
            self.assertIsNotNone(correlated)
            self.assertIn("malware.exe", correlated["summary"])


if __name__ == "__main__":
    unittest.main()
