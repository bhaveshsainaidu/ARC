"""
tests/test_startup_greeting.py — Unit tests for local-only startup greeting generation.
"""

import unittest
from core.greeting import build_startup_greeting_prompt, format_health_summary


class TestStartupGreeting(unittest.TestCase):

    def test_format_health_summary(self):
        system_status = {
            "cpu_percent": 12,
            "ram_percent": 45,
            "ram_used_gb": 7.2,
            "ram_total_gb": 16.0,
            "uptime": "2h 15m",
            "gpu_percent": 5,
        }
        summary = format_health_summary(system_status)
        self.assertIn("CPU 12%", summary)
        self.assertIn("memory 45%", summary)
        self.assertIn("7.2 of 16.0 GB", summary)
        self.assertIn("uptime 2h 15m", summary)
        self.assertIn("GPU 5%", summary)

    def test_build_startup_greeting_default(self):
        prompt = build_startup_greeting_prompt(
            time_str="14:30",
            system_status={"cpu_percent": 8, "ram_percent": 30, "ram_used_gb": 4.5, "ram_total_gb": 16.0, "uptime": "1h"},
        )
        self.assertTrue(prompt.startswith("[STARTUP_GREETING]"))
        self.assertIn("14:30", prompt)
        self.assertIn("CPU 8%", prompt)
        self.assertIn("Do not fetch news", prompt)

    def test_build_startup_greeting_with_identity(self):
        prompt = build_startup_greeting_prompt(
            time_str="09:00",
            system_status={"cpu_percent": 10, "ram_percent": 25, "ram_used_gb": 4.0, "ram_total_gb": 16.0, "uptime": "30m"},
            lang="Spanish",
            name="Bhavesh",
        )
        self.assertIn("Speak this greeting in Spanish", prompt)
        self.assertIn("Address the user as Bhavesh", prompt)

    def test_build_startup_greeting_with_last_session(self):
        prompt = build_startup_greeting_prompt(
            time_str="10:00",
            system_status={"cpu_percent": 5, "ram_percent": 20, "ram_used_gb": 3.2, "ram_total_gb": 16.0, "uptime": "10m"},
            last_session={"date": "2026-09-15", "summary": "Organized Downloads folder and checked battery health"},
        )
        self.assertIn("Organized Downloads folder", prompt)


if __name__ == "__main__":
    unittest.main()
