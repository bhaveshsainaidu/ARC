"""
tests/test_logger.py — Unit tests for structured logging and privacy redaction.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.logger import BhaveshLogger, sanitize_message


class TestLogger(unittest.TestCase):

    def test_sanitize_api_key(self):
        """Ensure Google API keys are automatically redacted."""
        fake_key = "AIzaSy" + "A" * 33
        raw_msg = f"Failed to connect using key {fake_key} to endpoint"
        sanitized = sanitize_message(raw_msg)
        self.assertNotIn(fake_key, sanitized)
        self.assertIn("[REDACTED_API_KEY]", sanitized)

    def test_sanitize_bearer_token(self):
        """Ensure Bearer tokens are automatically redacted."""
        raw_msg = "Headers: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
        sanitized = sanitize_message(raw_msg)
        self.assertIn("Bearer [REDACTED_TOKEN]", sanitized)

    def test_logger_categories_and_writing(self):
        """Ensure logger writes to rotating log file with correct format and categories."""
        with TemporaryDirectory() as tmp_dir:
            logger = BhaveshLogger(Path(tmp_dir))
            try:
                logger.audio("Microphone stream opened at 16000Hz")
                logger.gemini("Live session connected")
                logger.tool("computer_settings", "Adjusted volume to 50%")
                logger.dashboard("Client connected from 192.168.1.5")
                logger.system("Battery state: 85% charging")
                logger.error("Simulated non-critical error")

                logs = logger.get_recent_logs(20)
                self.assertEqual(len(logs), 6)
                self.assertTrue(any("[AUDIO]" in l for l in logs))
                self.assertTrue(any("[GEMINI]" in l for l in logs))
                self.assertTrue(any("[TOOLS]" in l for l in logs))
                self.assertTrue(any("[DASHBOARD]" in l for l in logs))
                self.assertTrue(any("[SYSTEM]" in l for l in logs))
                self.assertTrue(any("[ERROR]" in l for l in logs))
            finally:
                logger.close()


if __name__ == "__main__":
    unittest.main()
