"""Tests for Planner._extract_json – the static JSON extraction helper."""

import sys
import types
import unittest

# Mock heavy native deps before imports
for mod in ("pybullet", "pybullet_data"):
    sys.modules.setdefault(mod, types.ModuleType(mod))

from src.brain.planner import Planner


class TestExtractJson(unittest.TestCase):
    """Planner._extract_json should pull JSON from LLM output reliably."""

    def test_plain_json(self):
        text = '{"tool": "reset", "args": {}}'
        result = Planner._extract_json(text)
        self.assertIsNotNone(result)
        self.assertIn("reset", result)

    def test_json_with_whitespace(self):
        text = '  \n {"tool": "pick", "args": {"object": "cube_1"}}  \n'
        result = Planner._extract_json(text)
        self.assertIsNotNone(result)

    def test_json_in_markdown_fence(self):
        text = 'Here is the plan:\n```json\n{"tool": "reset", "args": {}}\n```\n'
        result = Planner._extract_json(text)
        self.assertIsNotNone(result)
        self.assertIn("reset", result)

    def test_json_in_plain_fence(self):
        text = '```\n{"tool": "pick", "args": {"object": "box"}}\n```'
        result = Planner._extract_json(text)
        self.assertIsNotNone(result)

    def test_returns_none_for_non_json(self):
        result = Planner._extract_json("I don't know how to do that.")
        self.assertIsNone(result)

    def test_returns_none_for_empty(self):
        self.assertIsNone(Planner._extract_json(""))

    def test_nested_json(self):
        text = '{"type":"plan","actions":[{"tool":"pick","args":{"object":"c"}}]}'
        result = Planner._extract_json(text)
        self.assertIsNotNone(result)
        self.assertIn("plan", result)


if __name__ == "__main__":
    unittest.main()
