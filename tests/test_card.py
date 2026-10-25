import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from windowping import card as card_mod
from windowping.bot import BotCommands
from windowping.config import Config, General, ProviderConfig, TelegramConfig
from windowping.providers.base import PingResult, Usage, Window
from windowping.watcher import PING, Watcher

NOW = 1_800_000_000.0


class CountingProvider:
    title = "Fake"

    def __init__(self, name="fake", usage_calls=0):
        self.name = name
        self.usage_calls = usage_calls
        self.pings = 0

    def usage(self):
        self.usage_calls += 1
        return Usage(
            provider=self.name,
            five=Window(pct=10, reset_at=NOW + 3600),
            weekly=Window(pct=20),
        )

    def ping(self):
        self.pings += 1
        return PingResult(ok=True, seconds=1.0, model="m", tokens=7)


def make_config(tmp, **general) -> Config:
    general.setdefault("usage_interval", 1800.0)
    return Config(
        general=General(state_file=Path(tmp) / "state.json", **general),
        providers={"fake": ProviderConfig(name="fake")},
        telegram=TelegramConfig(enabled=True, bot_token="t", chat_id=1),
    )


class UsageIntervalTest(unittest.TestCase):
    def test_usage_is_not_read_on_every_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CountingProvider()
            watcher = Watcher(make_config(tmp))
            with mock.patch("windowping.watcher.time.time", return_value=NOW):
                watcher.tick([provider])
                watcher.tick([provider])
            self.assertEqual(provider.usage_calls, 1)

    def test_usage_is_read_again_after_the_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CountingProvider()
            watcher = Watcher(make_config(tmp, usage_interval=1800.0))
            with mock.patch("windowping.watcher.time.time", return_value=NOW):
                watcher.tick([provider])
            with mock.patch("windowping.watcher.time.time", return_value=NOW + 1801):
                watcher.tick([provider])
            self.assertEqual(provider.usage_calls, 2)

    def test_refresh_forces_a_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CountingProvider()
            watcher = Watcher(make_config(tmp))
            with mock.patch("windowping.watcher.time.time", return_value=NOW):
                watcher.tick([provider])
                watcher.refresh_usage([provider])
            self.assertEqual(provider.usage_calls, 2)

    def test_a_cached_reading_survives_a_broken_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CountingProvider()
            watcher = Watcher(make_config(tmp, usage_interval=0.0))
            with mock.patch("windowping.watcher.time.time", return_value=NOW):
                watcher.tick([provider])
            provider.usage = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            with mock.patch("windowping.watcher.time.time", return_value=NOW + 10):
                results = watcher.tick([provider])
            self.assertIsNotNone(results[0].usage)      # the old numbers still stand
            self.assertIsNone(results[0].error)


class ResetReadTest(unittest.TestCase):
    def test_a_confirmed_reset_is_not_re_read_every_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CountingProvider()
            # A window that has already reset: the watcher wants one confirmation.
            provider.usage = lambda: Usage(
                provider="fake", five=Window(pct=100, reset_at=NOW - 600), weekly=Window(pct=10)
            )
            watcher = Watcher(make_config(tmp, usage_interval=1800.0, failed_ping_cooldown=0.0))
            with mock.patch("windowping.watcher.time.time", return_value=NOW):
                watcher.tick([provider])          # reads, pings, reads again (probe)
                calls_after_first = provider.usage_calls
                for _ in range(5):
                    watcher.tick([provider])
            self.assertEqual(provider.usage_calls, calls_after_first)

    def test_an_off_schedule_provider_is_not_read_every_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CountingProvider()
            provider.cfg = None
            provider.usage = lambda: Usage(
                provider="fake", five=Window(pct=100, reset_at=NOW - 600), weekly=Window(pct=10)
            )
            config = make_config(tmp, usage_interval=1800.0, failed_ping_cooldown=0.0)
            from windowping.config import ProviderConfig
            provider.cfg = ProviderConfig(name="fake", options={"schedule": "never"})
            watcher = Watcher(config)
            with mock.patch("windowping.watcher.time.time", return_value=NOW):
                watcher.tick([provider])
                calls = provider.usage_calls
                for _ in range(5):
                    watcher.tick([provider])
            self.assertEqual(provider.usage_calls, calls)


class CardRenderTest(unittest.TestCase):
    def test_keyboard_has_every_button(self):
        buttons = [b["callback_data"] for row in card_mod.keyboard("en")["inline_keyboard"] for b in row]
        self.assertEqual(buttons, ["refresh", "ping", "stats", "schedule", "mute"])

    def test_card_shows_provider_and_footer(self):
        usage = Usage(provider="fake", five=Window(pct=10, reset_at=NOW + 3600), weekly=Window(pct=20), plan="plus")
        text = card_mod.render(
            [("Fake", usage, None)],
            NOW,
            lang="ru",
            updated_at=NOW,
            next_at=NOW + 600,
        )
        self.assertIn("Fake", text)
        self.assertIn("авто в", text)


class PublisherTest(unittest.TestCase):
    def test_first_publish_sends_then_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher = Watcher(make_config(tmp))
            publisher = card_mod.CardPublisher(watcher.config.telegram, watcher.state)
            with mock.patch.object(card_mod, "send_message", return_value=4242) as send, \
                 mock.patch.object(card_mod, "edit_message", return_value=True) as edit:
                publisher.publish("first", "en")
                publisher.publish("second", "en")
            send.assert_called_once()
            edit.assert_called_once()
            self.assertEqual(watcher.state.data["card_message_id"], 4242)

    def test_unchanged_card_is_not_resent(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher = Watcher(make_config(tmp))
            publisher = card_mod.CardPublisher(watcher.config.telegram, watcher.state)
            with mock.patch.object(card_mod, "send_message", return_value=4242) as send, \
                 mock.patch.object(card_mod, "edit_message", return_value=True) as edit:
                publisher.publish("same", "en")
                publisher.publish("same", "en")
            send.assert_called_once()
            edit.assert_not_called()


class CallbackTest(unittest.TestCase):
    def test_refresh_reads_usage_and_repaints(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            watcher = Watcher(config)
            bot = BotCommands(config, watcher)
            with mock.patch.object(watcher, "refresh_usage", return_value=[]) as refresh:
                bot.handle_callback("refresh", 1, 10, "en")
            refresh.assert_called_once()

    def test_mute_sets_the_deadline_and_repaints(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            watcher = Watcher(config)
            bot = BotCommands(config, watcher)
            with mock.patch.object(watcher, "repaint_card") as repaint:
                bot.handle_callback("mute", 1, 10, "en")
            self.assertGreater(watcher.muted_until(), time.time())
            repaint.assert_called_once()

    def test_status_repaints_without_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            watcher = Watcher(config)
            bot = BotCommands(config, watcher)
            with mock.patch.object(watcher, "repaint_card") as repaint, \
                 mock.patch.object(watcher, "refresh_usage") as refresh:
                bot.handle_callback("status", 1, 10, "en")
            repaint.assert_called_once()
            refresh.assert_not_called()

    def test_stats_and_schedule_send_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            watcher = Watcher(config)
            bot = BotCommands(config, watcher)
            with mock.patch("windowping.bot.send_message", return_value=1) as send:
                bot.handle_callback("stats", 1, 10, "en")
                bot.handle_callback("schedule", 1, 10, "en")
            self.assertEqual(send.call_count, 2)


class PollerCallbackTest(unittest.TestCase):
    def test_callback_query_reaches_the_handler(self):
        from windowping.notify.telegram import TelegramPoller

        cfg = TelegramConfig(enabled=True, bot_token="t", chat_id=1)
        seen = []

        def on_callback(data, chat_id, message_id, lang):
            seen.append((data, chat_id, message_id))

        poller = TelegramPoller(cfg, lambda text, lang=None: None, on_callback)
        update = {
            "update_id": 5,
            "callback_query": {
                "id": "cb1",
                "data": "refresh",
                "message": {"message_id": 103, "chat": {"id": 1}},
                "from": {"language_code": "ru"},
            },
        }
        with mock.patch("windowping.notify.telegram.answer_callback") as answer:
            poller.handle_update(update)
        answer.assert_called_once()
        self.assertEqual(seen, [("refresh", 1, 103)])

    def test_a_plain_message_still_works(self):
        from windowping.notify.telegram import TelegramPoller

        cfg = TelegramConfig(enabled=True, bot_token="t", chat_id=1)
        seen = []
        poller = TelegramPoller(cfg, lambda text, lang=None: seen.append(text) or None)
        with mock.patch("windowping.notify.telegram.send_message", return_value=1):
            poller.handle_update({"update_id": 6, "message": {"chat": {"id": 1}, "text": "/status"}})
        self.assertEqual(seen, ["/status"])


class BatchPingTest(unittest.TestCase):
    def test_two_pings_in_one_tick_are_one_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, failed_ping_cooldown=0.0)
            first = CountingProvider("fake")
            second = CountingProvider("fake2")
            collector = []

            class Sink:
                def notify(self, event, text):
                    collector.append((event, text))

            watcher = Watcher(config, Sink())
            # A window that has just reset: both providers want a ping.
            for provider in (first, second):
                provider.usage = lambda p=provider: Usage(
                    provider=p.name, five=Window(pct=100, reset_at=NOW - 600), weekly=Window(pct=10)
                )
            with mock.patch("windowping.watcher.time.time", return_value=NOW):
                watcher.tick([first, second])
            pings = [item for item in collector if item[0] == PING]
            self.assertEqual(len(pings), 1)
            self.assertIn("2", pings[0][1])


if __name__ == "__main__":
    unittest.main()
