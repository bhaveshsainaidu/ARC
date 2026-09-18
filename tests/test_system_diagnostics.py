"""
tests/test_system_diagnostics.py — Unit tests for local system diagnostics action.
Ensures diagnostics report readiness, include hardware metrics, and never leak keys.
"""

import unittest
from actions.system_diagnostics import system_diagnostics, TOOL


class TestSystemDiagnostics(unittest.TestCase):

    def test_tool_declaration_structure(self):
        """Verify TOOL declaration conforms to Gemini function schema."""
        self.assertEqual(TOOL["name"], "system_diagnostics")
        self.assertIn("description", TOOL)
        self.assertEqual(TOOL["parameters"]["type"], "OBJECT")
        self.assertTrue(callable(TOOL["handler"]))

    def test_diagnostics_execution(self):
        """Verify system_diagnostics returns a formatted local status string."""
        report = system_diagnostics({})
        self.assertIsInstance(report, str)
        self.assertIn("SYSTEM READINESS:", report)
        self.assertIn("Windows/platform:", report)
        self.assertIn("CPU:", report)
        self.assertIn("Audio:", report)

        # Crucial security check: Ensure no API key or token substrings appear in output
        self.assertNotIn("AIza", report)
        self.assertNotIn("Bearer", report)


if __name__ == "__main__":
    unittest.main()
