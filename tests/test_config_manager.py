"""
tests/test_config_manager.py — Unit tests for configuration management.
Ensures config settings are safely read and updated without exposing or modifying live secrets.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from memory import config_manager


class TestConfigManager(unittest.TestCase):

    def test_assistant_name_and_user_name(self):
        """Verify assistant name and user name can be set and retrieved independently."""
        with TemporaryDirectory() as tmp_dir:
            tmp_cfg = Path(tmp_dir) / "api_keys.json"
            with patch.object(config_manager, "CONFIG_FILE", tmp_cfg), \
                 patch.object(config_manager, "CONFIG_DIR", Path(tmp_dir)):
                
                # Initially unconfigured
                self.assertFalse(config_manager.is_configured())

                # Save assistant name
                config_manager.save_assistant_config("Bhavesh", "Alex")
                self.assertEqual(config_manager.get_assistant_name(), "Bhavesh")
                self.assertEqual(config_manager.get_user_name(), "Alex")

    def test_voice_selection_fallback(self):
        """Unknown or invalid voice names must safely collapse to DEFAULT_VOICE."""
        with TemporaryDirectory() as tmp_dir:
            tmp_cfg = Path(tmp_dir) / "api_keys.json"
            with patch.object(config_manager, "CONFIG_FILE", tmp_cfg), \
                 patch.object(config_manager, "CONFIG_DIR", Path(tmp_dir)):

                config_manager.save_voice("NonExistentVoice")
                self.assertEqual(config_manager.get_voice(), config_manager.DEFAULT_VOICE)

                config_manager.save_voice("Fenrir")
                self.assertEqual(config_manager.get_voice(), "Fenrir")

    def test_audio_device_persistence(self):
        """Audio device selections should be stored and retrieved cleanly."""
        with TemporaryDirectory() as tmp_dir:
            tmp_cfg = Path(tmp_dir) / "api_keys.json"
            with patch.object(config_manager, "CONFIG_FILE", tmp_cfg), \
                 patch.object(config_manager, "CONFIG_DIR", Path(tmp_dir)):

                config_manager.save_input_device("USB Microphone")
                config_manager.save_output_device("Headphones")
                self.assertEqual(config_manager.get_input_device(), "USB Microphone")
                self.assertEqual(config_manager.get_output_device(), "Headphones")

    def test_plugin_config_persistence(self):
        """Custom plugin namespace settings are safely stored and merged."""
        with TemporaryDirectory() as tmp_dir:
            tmp_cfg = Path(tmp_dir) / "api_keys.json"
            with patch.object(config_manager, "CONFIG_FILE", tmp_cfg), \
                 patch.object(config_manager, "CONFIG_DIR", Path(tmp_dir)):

                config_manager.save_plugin_config("smart_lights", {"ip": "192.168.1.100", "key": "abc"})
                cfg = config_manager.get_plugin_config("smart_lights")
                self.assertEqual(cfg.get("ip"), "192.168.1.100")
                self.assertEqual(config_manager.get_plugin_setting("smart_lights", "key"), "abc")


if __name__ == "__main__":
    unittest.main()
