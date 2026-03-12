"""Tests for src.config – Config defaults and parse_args."""

import sys
import unittest

from src.config import Config, parse_args


class TestConfigDefaults(unittest.TestCase):
    """Config dataclass should expose sensible defaults."""

    def test_default_model(self):
        cfg = Config()
        self.assertEqual(cfg.foundry_model_alias, "qwen2.5-coder-0.5b")

    def test_default_whisper_model(self):
        cfg = Config()
        self.assertEqual(cfg.whisper_model_alias, "whisper-base")

    def test_default_input_mode(self):
        cfg = Config()
        self.assertEqual(cfg.input_mode, "text")

    def test_default_api_key(self):
        cfg = Config()
        self.assertEqual(cfg.api_key, "not-required")

    def test_default_temperature(self):
        cfg = Config()
        self.assertAlmostEqual(cfg.temperature, 0.1)

    def test_default_workspace_bounds(self):
        cfg = Config()
        self.assertLess(cfg.ws_x_min, cfg.ws_x_max)
        self.assertLess(cfg.ws_y_min, cfg.ws_y_max)
        self.assertLess(cfg.ws_z_min, cfg.ws_z_max)

    def test_dry_run_default_false(self):
        cfg = Config()
        self.assertFalse(cfg.dry_run)

    def test_gui_default_true(self):
        cfg = Config()
        self.assertTrue(cfg.use_gui)


class TestParseArgs(unittest.TestCase):
    """parse_args should translate CLI flags into a Config."""

    def _parse(self, args: list[str]) -> Config:
        orig = sys.argv
        sys.argv = ["prog"] + args
        try:
            return parse_args()
        finally:
            sys.argv = orig

    def test_defaults(self):
        cfg = self._parse([])
        self.assertEqual(cfg.input_mode, "text")
        self.assertFalse(cfg.dry_run)

    def test_voice_mode(self):
        cfg = self._parse(["--mode", "voice"])
        self.assertEqual(cfg.input_mode, "voice")

    def test_dry_run(self):
        cfg = self._parse(["--dry-run"])
        self.assertTrue(cfg.dry_run)

    def test_custom_model(self):
        cfg = self._parse(["--model", "my-model"])
        self.assertEqual(cfg.foundry_model_alias, "my-model")


if __name__ == "__main__":
    unittest.main()
