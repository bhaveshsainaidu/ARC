"""
tests/test_plugin_loader.py — Unit tests for drop-in plugin discovery, validation, and execution.
"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.plugin_loader import discover_plugins, PluginRegistry, PluginRecord


class TestPluginLoader(unittest.TestCase):

    def test_discover_plugins_in_temp_dir(self):
        """Verify discover_plugins finds, validates and enables valid plugins."""
        with TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            plugin_code = (
                "def run(parameters, **kw):\n"
                "    return 'Plugin Result: ' + str(parameters.get('val'))\n"
                "PLUGIN = {\n"
                "    'name': 'test_plugin',\n"
                "    'description': 'A test plugin',\n"
                "    'parameters': {'type': 'OBJECT', 'properties': {}},\n"
                "    'run': run,\n"
                "}\n"
            )
            (p / "sample_plugin.py").write_text(plugin_code, encoding="utf-8")

            # Also a template / underscore file that should be skipped
            (p / "_template.py").write_text("# template only", encoding="utf-8")

            reg = discover_plugins(p, core_tool_names=set(), logger=lambda m: None)
            self.assertIsInstance(reg, PluginRegistry)
            self.assertTrue(reg.has("test_plugin"))
            self.assertFalse(reg.has("_template"))

            # Test tool declaration
            decls = reg.get_tool_declarations()
            self.assertEqual(len(decls), 1)
            self.assertEqual(decls[0]["name"], "test_plugin")

            # Test execution
            res = reg.run("test_plugin", {"val": 42})
            self.assertEqual(res, "Plugin Result: 42")

    def test_plugin_settings_schema(self):
        """Plugins declaring PLUGIN_SETTINGS should expose schemas for the HUD."""
        with TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            plugin_code = (
                "def run(parameters, **kw):\n"
                "    return 'ok'\n"
                "PLUGIN = {\n"
                "    'name': 'configured_plugin',\n"
                "    'description': 'Has settings',\n"
                "    'parameters': {'type': 'OBJECT', 'properties': {}},\n"
                "    'run': run,\n"
                "}\n"
                "PLUGIN_SETTINGS = {\n"
                "    'title': 'My Config',\n"
                "    'namespace': 'test_ns',\n"
                "    'fields': [{'key': 'api_url', 'label': 'API URL', 'type': 'text'}],\n"
                "}\n"
            )
            (p / "configured_plugin.py").write_text(plugin_code, encoding="utf-8")

            reg = discover_plugins(p, core_tool_names=set(), logger=lambda m: None)
            schemas = reg.settings_schemas()
            self.assertEqual(len(schemas), 1)
            self.assertEqual(schemas[0]["title"], "My Config")
            self.assertEqual(schemas[0]["namespace"], "test_ns")


if __name__ == "__main__":
    unittest.main()
