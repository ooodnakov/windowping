import tempfile
import unittest
from pathlib import Path

from windowping.bot import BotCommands
from windowping.config import Config, General, ProviderConfig, TelegramConfig
from windowping.watcher import Watcher


def make_config(tmp: str, schedules: dict[str, str]) -> Config:
    providers = {}
    for name, schedule in schedules.items():
        options = {"schedule": schedule} if schedule else {}
        providers[name] = ProviderConfig(name=name, options=options)
    return Config(
        general=General(state_file=Path(tmp) / "state.json"),
        providers=providers,
        telegram=TelegramConfig(enabled=True, bot_token="t", chat_id=1),
    )


class ScheduleCommandTest(unittest.TestCase):
    def test_lists_configured_schedules(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, {"glm": "mon-fri", "commandcode": ""})
            bot = BotCommands(config, Watcher(config))
            text = bot.handle("/schedule", sender_lang="en")
            assert text is not None
            self.assertIn("Ping schedule", text)
            self.assertIn("mon-fri", text)
            self.assertIn("always", text)

    def test_filters_to_one_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, {"glm": "mon-fri", "codex": "always"})
            bot = BotCommands(config, Watcher(config))
            text = bot.handle("/schedule glm", sender_lang="en")
            assert text is not None
            self.assertIn("GLM", text)
            self.assertIn("mon-fri", text)

    def test_unknown_provider_is_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, {"glm": "mon-fri"})
            bot = BotCommands(config, Watcher(config))
            text = bot.handle("/schedule nope", sender_lang="en")
            assert text is not None
            self.assertIn("Ping schedule", text)


if __name__ == "__main__":
    unittest.main()
