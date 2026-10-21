import tempfile
import unittest
from pathlib import Path

from windowping.config import (
    DEFAULT_CONFIG_TEXT,
    TelegramConfig,
    load,
    parse_duration,
    write_default_config,
)


class ParseDurationTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_duration("90s", 0), 90)
        self.assertEqual(parse_duration("5m", 0), 300)
        self.assertEqual(parse_duration("2h", 0), 7200)
        self.assertEqual(parse_duration("1d", 0), 86400)
        self.assertEqual(parse_duration(45, 0), 45)
        self.assertEqual(parse_duration("30", 0), 30)

    def test_default_and_errors(self):
        self.assertEqual(parse_duration(None, 7), 7)
        self.assertEqual(parse_duration("", 7), 7)
        with self.assertRaises(ValueError):
            parse_duration("soon", 0)


class LoadTest(unittest.TestCase):
    def test_defaults_are_written_and_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            write_default_config(path)
            self.assertTrue(path.exists())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_text(encoding="utf-8"), DEFAULT_CONFIG_TEXT)

            config = load(path)
            self.assertEqual(config.general.reset_buffer, 300)
            self.assertEqual(config.general.tick_interval, 60)
            self.assertAlmostEqual(config.general.weekly_threshold, 0.99)
            self.assertEqual(
                sorted(config.providers), ["codex", "commandcode", "glm"]
            )
            self.assertTrue(all(p.enabled for p in config.providers.values()))
            self.assertFalse(config.telegram.active)

    def test_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                """
[general]
reset_buffer = "90s"
weekly_threshold = 0.95

[providers.glm]
enabled = false
model = "glm-5.3"

[telegram]
enabled = true
bot_token = "123:abc"
chat_id = 42
notify_events = ["ping"]
""",
                encoding="utf-8",
            )
            config = load(path)
            self.assertEqual(config.general.reset_buffer, 90)
            self.assertAlmostEqual(config.general.weekly_threshold, 0.95)
            self.assertFalse(config.providers["glm"].enabled)
            self.assertEqual(config.providers["glm"].get("model"), "glm-5.3")
            self.assertTrue(config.telegram.active)
            self.assertEqual(config.telegram.allow_chat_ids, (42,))
            self.assertEqual(config.telegram.notify_events, ("ping",))

    def test_chat_id_zero_disables_delivery(self):
        telegram = TelegramConfig(enabled=True, bot_token="x", chat_id=None)
        self.assertFalse(telegram.active)


if __name__ == "__main__":
    unittest.main()
