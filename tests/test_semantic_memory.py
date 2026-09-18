"""
tests/test_semantic_memory.py — Unit tests for Persistent Personalized Memory & Learning System.
Tests local dense vector retrieval, conceptual fallback, conflict superseding,
feedback ingestion, prompt formatting, and UI integration.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from memory import memory_manager


class TestSemanticMemory(unittest.TestCase):

    def test_semantic_retrieval_cross_context(self):
        """Verify cross-language and semantic concept retrieval."""
        # Java null check query should surface defensive null check lesson (which mentions Java and Python)
        results = memory_manager.retrieve_semantic_memories("How to handle Java NullPointerException?", top_k=2)
        self.assertTrue(len(results) > 0)
        top_concepts = [r.get("concept") for r in results]
        self.assertIn("defensive_null_and_error_handling", top_concepts)

        # Indentation query
        indent_results = memory_manager.retrieve_semantic_memories("How many spaces should I indent python code?", top_k=2)
        self.assertTrue(len(indent_results) > 0)
        self.assertIn("code_formatting_indentation", [r.get("concept") for r in indent_results])

    def test_conceptual_fallback_engine(self):
        """Verify fallback BM25/concept expansion works when SentenceTransformer is unavailable."""
        engine = memory_manager.get_semantic_engine()
        with patch.object(engine, "_get_model", return_value=None):
            results = engine.retrieve("Java null check error handling", top_k=2)
            self.assertTrue(len(results) > 0)
            self.assertIn("defensive_null_and_error_handling", [r.get("concept") for r in results])

    def test_conflict_superseding(self):
        """Verify user corrections supersede conflicting older memories."""
        with TemporaryDirectory() as tmp_dir:
            tmp_store = Path(tmp_dir) / "test_semantic_store.json"
            initial_data = {
                "version": 1,
                "last_updated": "2026-09-16T12:00:00",
                "memories": [
                    {
                        "id": "mem_old_001",
                        "concept": "code_style_quotes",
                        "lesson": "Always use double quotes for strings in Python.",
                        "type": "preference",
                        "source": "preference",
                        "priority": 8,
                        "tags": ["quotes", "python", "style"],
                        "timestamp": "2026-09-16T12:00:00",
                        "active": True,
                        "superseded_by": None,
                        "context": "Initial code style",
                    }
                ],
            }
            tmp_store.write_text(json.dumps(initial_data), encoding="utf-8")

            with patch.object(memory_manager, "SEMANTIC_PATH", tmp_store):
                # Add higher priority correction
                new_mem = memory_manager.add_semantic_memory(
                    lesson="Actually, strictly use single quotes for internal strings.",
                    concept="code_style_quotes",
                    mem_type="correction",
                    source="user_correction",
                    priority=10,
                    tags=["quotes", "python", "style", "single"],
                )

                # Verify store state
                loaded = json.loads(tmp_store.read_text(encoding="utf-8"))
                memories = loaded["memories"]
                self.assertEqual(len(memories), 2)

                old_entry = next(m for m in memories if m["id"] == "mem_old_001")
                self.assertFalse(old_entry["active"])
                self.assertEqual(old_entry["superseded_by"], new_mem["id"])

                new_entry = next(m for m in memories if m["id"] == new_mem["id"])
                self.assertTrue(new_entry["active"])
                self.assertIsNone(new_entry["superseded_by"])

                # Verify retrieval only returns the active new memory
                retrieved = memory_manager.retrieve_semantic_memories("python quotes style preference", top_k=2)
                active_ids = [m["id"] for m in retrieved]
                self.assertIn(new_mem["id"], active_ids)
                self.assertNotIn("mem_old_001", active_ids)

    def test_feedback_detection_and_ingestion(self):
        """Verify automatic detection and parsing of user corrections and feedback."""
        with TemporaryDirectory() as tmp_dir:
            tmp_store = Path(tmp_dir) / "test_semantic_store.json"
            tmp_store.write_text(json.dumps({"version": 1, "last_updated": "", "memories": []}), encoding="utf-8")

            with patch.object(memory_manager, "SEMANTIC_PATH", tmp_store):
                # Test correction phrase
                res1 = memory_manager.detect_and_ingest_feedback(
                    "That's wrong, always check if directory exists before saving files.",
                    previous_asst_turn="Saved file directly.",
                )
                self.assertIsNotNone(res1)
                self.assertEqual(res1["type"], "correction")
                self.assertEqual(res1["priority"], 10)
                self.assertIn("directory", res1["lesson"].lower())

                # Test preference phrase
                res2 = memory_manager.detect_and_ingest_feedback("I prefer dark mode on all mobile screens.")
                self.assertIsNotNone(res2)
                self.assertEqual(res2["type"], "preference")
                self.assertEqual(res2["priority"], 8)

                # Test standing instruction / lesson phrase
                res3 = memory_manager.detect_and_ingest_feedback("From now on, always reply with short summaries.")
                self.assertIsNotNone(res3)
                self.assertEqual(res3["type"], "lesson")

                # Test ordinary conversational phrase (should not ingest)
                res_none = memory_manager.detect_and_ingest_feedback("Can you check the current weather in London?")
                self.assertIsNone(res_none)

    def test_format_semantic_context_for_prompt(self):
        """Verify prompt formatting injects relevant learned rules."""
        ctx = memory_manager.format_semantic_context_for_prompt("Java null pointer check")
        self.assertIn("[RELEVANT LEARNED CONTEXT & USER CORRECTIONS]", ctx)
        self.assertIn("Defensive Null And Error Handling", ctx)

        # Unrelated query should return empty string
        empty_ctx = memory_manager.format_semantic_context_for_prompt("nonexistent_random_unrelated_query_12345")
        self.assertEqual(empty_ctx, "")

    def test_ui_integration_and_forget(self):
        """Verify learned memories surface in UI list and can be forgotten."""
        with TemporaryDirectory() as tmp_dir:
            tmp_store = Path(tmp_dir) / "test_semantic_store.json"
            initial_data = {
                "version": 1,
                "last_updated": "2026-09-16T12:00:00",
                "memories": [
                    {
                        "id": "mem_ui_001",
                        "concept": "ui_test_rule",
                        "lesson": "Test rule for UI display.",
                        "type": "lesson",
                        "source": "user_correction",
                        "priority": 9,
                        "tags": ["ui", "test"],
                        "timestamp": "2026-09-16T12:00:00",
                        "active": True,
                        "superseded_by": None,
                        "context": "UI test context",
                    }
                ],
            }
            tmp_store.write_text(json.dumps(initial_data), encoding="utf-8")

            with patch.object(memory_manager, "SEMANTIC_PATH", tmp_store):
                entries = memory_manager.all_entries_for_ui()
                ui_match = [e for e in entries if e["key"] == "ui_test_rule"]
                self.assertTrue(len(ui_match) > 0)
                self.assertEqual(ui_match[0]["category"], "learned (lesson)")

                # Test forget
                msg = memory_manager.forget("ui_test_rule", category="learned (lesson)")
                self.assertIn("Forgotten learned memory", msg)

                # Verify deactivated in store
                loaded = json.loads(tmp_store.read_text(encoding="utf-8"))
                self.assertFalse(loaded["memories"][0]["active"])


if __name__ == "__main__":
    unittest.main()
