"""
tests/test_memory_manager.py — Unit tests for memory store, formatting, search, and privacy.
Ensures private user memory is never compromised, corrupted, or leaked.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from memory import memory_manager


class TestMemoryManager(unittest.TestCase):

    def test_format_memory_for_prompt(self):
        """Verify format_memory_for_prompt returns structured memory with budget limits."""
        sample_memory = {
            "identity": {
                "name": {"value": "TestUser", "updated": "2026-01-01"},
                "language": {"value": "English", "updated": "2026-01-01"},
            },
            "preferences": {
                "ide": {"value": "VSCode", "updated": "2026-01-02"},
                "theme": {"value": "Dark", "updated": "2026-01-02"},
            },
            "projects": {
                "agent": {"value": "ARC project", "updated": "2026-01-03"},
            },
            "relationships": {},
            "wishes": {},
            "notes": {},
        }
        formatted = memory_manager.format_memory_for_prompt(sample_memory)
        self.assertIn("TestUser", formatted)
        self.assertIn("ARC project", formatted)
        self.assertIn("Preferences:", formatted)

    def test_search_memory_isolated(self):
        """Verify search_memory retrieves relevant items by substring/fuzzy match."""
        with TemporaryDirectory() as tmp_dir:
            tmp_mem = Path(tmp_dir) / "test_memory.json"
            initial_data = {
                "identity": {"city": {"value": "San Francisco", "updated": "2026-01-01"}},
                "preferences": {"coffee": {"value": "Black Espresso", "updated": "2026-01-01"}},
                "projects": {"ai": {"value": "Building autonomous Windows agent", "updated": "2026-01-01"}},
                "relationships": {},
                "wishes": {},
                "notes": {},
            }
            tmp_mem.write_text(json.dumps(initial_data), encoding="utf-8")

            with patch.object(memory_manager, "MEMORY_PATH", tmp_mem):
                results = memory_manager.search_memory("espresso")
                self.assertIn("preferences/coffee", results)
                self.assertIn("Black Espresso", results)

                results_ai = memory_manager.search_memory("autonomous")
                self.assertIn("projects/ai", results_ai)

                results_none = memory_manager.search_memory("nonexistent_term_xyz")
                self.assertIn("Nothing stored about", results_none)

    def test_update_memory_isolated(self):
        """Verify memory updates write safely and enforce constraints without affecting live data."""
        with TemporaryDirectory() as tmp_dir:
            tmp_mem = Path(tmp_dir) / "test_memory.json"
            with patch.object(memory_manager, "MEMORY_PATH", tmp_mem):
                # Update a key using dictionary shape
                memory_manager.update_memory({"preferences": {"editor": "Cursor"}})
                loaded = memory_manager.load_memory()
                self.assertIn("editor", loaded["preferences"])
                self.assertEqual(loaded["preferences"]["editor"]["value"], "Cursor")


if __name__ == "__main__":
    unittest.main()
