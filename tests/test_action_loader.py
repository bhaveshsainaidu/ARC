"""
tests/test_action_loader.py — Unit tests for action discovery, validation, and execution.
"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.action_loader import ActionRecord, ActionRegistry, discover_actions, _validate


class TestActionLoader(unittest.TestCase):

    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.actions_dir = self.base_dir / "actions"

    def test_discover_bundled_actions(self):
        """Verify discover_actions finds and validates all 17 bundled actions."""
        registry = discover_actions(self.actions_dir, logger=lambda m: None)
        self.assertIsInstance(registry, ActionRegistry)
        names = registry.names()
        self.assertGreaterEqual(len(names), 17)

        expected_core_actions = [
            "browser_control",
            "code_helper",
            "computer_control",
            "computer_settings",
            "desktop_control",
            "dev_agent",
            "file_controller",
            "file_processor",
            "open_app",
            "reminder",
            "system_diagnostics",
            "weather_report",
            "web_search",
        ]
        for act in expected_core_actions:
            self.assertIn(act, names, f"Expected action '{act}' not discovered")

    def test_tool_declarations_format(self):
        """Tool declarations must match the schema expected by Gemini Live."""
        registry = discover_actions(self.actions_dir, logger=lambda m: None)
        decls = registry.get_tool_declarations()
        self.assertGreaterEqual(len(decls), 17)

        for decl in decls:
            self.assertIn("name", decl)
            self.assertIn("description", decl)
            self.assertIn("parameters", decl)
            self.assertTrue(decl["name"].isidentifier(), f"Name {decl['name']} is not valid identifier")
            self.assertEqual(decl["parameters"].get("type"), "OBJECT")

    def test_reserved_name_collision(self):
        """Actions colliding with reserved core names must be rejected."""
        reserved = {"screen_process", "system_status"}
        registry = discover_actions(self.actions_dir, reserved_names=reserved, logger=lambda m: None)
        for r in reserved:
            self.assertNotIn(r, registry.names())

    def test_invalid_action_rejection(self):
        """Files without TOOL dict or with invalid structure must be safely skipped without crashing."""
        with TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            # File 1: No TOOL dict
            (p / "no_tool.py").write_text("def hello(): pass", encoding="utf-8")
            # File 2: TOOL is not a dict
            (p / "bad_tool_type.py").write_text("TOOL = 'invalid'", encoding="utf-8")
            # File 3: Missing handler
            (p / "no_handler.py").write_text("TOOL = {'name': 'foo', 'description': 'bar'}", encoding="utf-8")
            # File 4: Valid action
            (p / "valid_tool.py").write_text(
                "def my_func(parameters, **kw): return 'ok'\n"
                "TOOL = {'name': 'custom_action', 'description': 'test', 'parameters': {'type': 'OBJECT', 'properties': {}}, 'handler': my_func}",
                encoding="utf-8"
            )

            registry = discover_actions(p, logger=lambda m: None)
            self.assertIn("custom_action", registry.names())
            self.assertNotIn("no_tool", registry.names())
            self.assertNotIn("bad_tool_type", registry.names())
            self.assertNotIn("no_handler", registry.names())

    def test_run_action_handler(self):
        """Registry.run executes the handler safely and passes kwargs."""
        with TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            (p / "echo_tool.py").write_text(
                "def echo(parameters, player=None, **kw):\n"
                "    return f'Echo: {parameters.get(\"msg\")} | player={player}'\n"
                "TOOL = {'name': 'echo', 'description': 'echoes', 'parameters': {'type': 'OBJECT'}, 'handler': echo}",
                encoding="utf-8"
            )
            registry = discover_actions(p, logger=lambda m: None)
            res = registry.run("echo", {"msg": "hello"}, ctx={"player": "MockPlayer"})
            self.assertEqual(res, "Echo: hello | player=MockPlayer")


if __name__ == "__main__":
    unittest.main()
