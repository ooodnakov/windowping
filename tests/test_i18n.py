import tempfile
import unittest
from pathlib import Path

from windowping.config import TelegramConfig
from windowping.i18n import STRINGS, help_text, normalize, t
from windowping.state import State


class NormalizeTest(unittest.TestCase):
    def test_supported(self):
        self.assertEqual(normalize("ru"), "ru")
        self.assertEqual(normalize("RU"), "ru")
        self.assertEqual(normalize("ru-RU"), "ru")
        self.assertEqual(normalize("ru_RU"), "ru")

    def test_fallback(self):
        self.assertEqual(normalize(None), "en")
        self.assertEqual(normalize(""), "en")
        self.assertEqual(normalize("en-GB"), "en")
        self.assertEqual(normalize("de"), "en")


class CatalogueTest(unittest.TestCase):
    def test_same_keys_in_every_language(self):
        keys = set(STRINGS["en"])
        for lang, table in STRINGS.items():
            self.assertEqual(set(table), keys, f"{lang} has a different key set")

    def test_unknown_key_returns_key(self):
        self.assertEqual(t("ru", "no_such_key"), "no_such_key")

    def test_values_are_substituted(self):
        self.assertIn("7", t("en", "detail_reset_credits", count=7))
        self.assertIn("7", t("ru", "detail_reset_credits", count=7))

    def test_help_per_language(self):
        en, ru = help_text("en"), help_text("ru")
        self.assertIn("Commands", en)
        self.assertIn("Команды", ru)
        self.assertNotEqual(en, ru)
        for text in (en, ru):
            self.assertIn("/status", text)
            self.assertIn("/ping", text)

    def test_help_name_is_substituted(self):
        self.assertIn("<b>windowping</b>", help_text("en"))
        self.assertIn("<b>other</b>", help_text("en", "other"))


class TelegramConfigLangTest(unittest.TestCase):
    def test_auto_follows_sender(self):
        cfg = TelegramConfig(lang="auto")
        self.assertEqual(cfg.resolve_lang("ru-RU"), "ru")
        self.assertEqual(cfg.resolve_lang("en"), "en")
        self.assertEqual(cfg.resolve_lang(None), "en")

    def test_pinned_language_wins(self):
        self.assertEqual(TelegramConfig(lang="ru").resolve_lang("en-US"), "ru")
        self.assertEqual(TelegramConfig(lang="en").resolve_lang("ru"), "en")

    def test_junk_language_falls_back_to_english(self):
        self.assertEqual(TelegramConfig(lang="klingon").resolve_lang("ru"), "en")


class ChatLangStoreTest(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = State(path)
            self.assertIsNone(state.chat_lang(123))
            state.set_chat_lang(123, "ru")
            state.save()
            self.assertEqual(State(path).chat_lang(123), "ru")
            self.assertIsNone(state.chat_lang(None))


if __name__ == "__main__":
    unittest.main()
