import os
import socket
import tempfile
import unittest
from pathlib import Path

from windowping import sdnotify
from windowping.config import Config, General, ProviderConfig, TelegramConfig
from windowping.providers.base import PingResult, Usage, Window
from windowping.state import State
from windowping.watcher import ESCALATE, ERROR, Watcher


class SdNotifyTest(unittest.TestCase):
    def test_noop_without_the_socket(self):
        os.environ.pop("NOTIFY_SOCKET", None)
        self.assertFalse(sdnotify.enabled())
        self.assertFalse(sdnotify.ready())
        self.assertFalse(sdnotify.watchdog())

    def test_datagram_reaches_the_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "notify.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            server.bind(path)
            server.settimeout(2.0)
            os.environ["NOTIFY_SOCKET"] = path
            try:
                self.assertTrue(sdnotify.ready())
                self.assertEqual(server.recv(64), b"READY=1")
                self.assertTrue(sdnotify.watchdog())
                self.assertEqual(server.recv(64), b"WATCHDOG=1")
                self.assertTrue(sdnotify.stopping())
                self.assertEqual(server.recv(64), b"STOPPING=1")
            finally:
                os.environ.pop("NOTIFY_SOCKET", None)
                server.close()

    def test_unreachable_socket_does_not_raise(self):
        os.environ["NOTIFY_SOCKET"] = "/nonexistent/notify.sock"
        try:
            self.assertFalse(sdnotify.ready())
        finally:
            os.environ.pop("NOTIFY_SOCKET", None)


class FailingProvider:
    name = "fake"
    title = "Fake"

    def __init__(self, ok: bool = False):
        self.ok = ok
        self.pings = 0

    def usage(self):
        return Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))

    def ping(self):
        self.pings += 1
        return PingResult(ok=self.ok, error=None if self.ok else "boom")


class Collector:
    def __init__(self):
        self.events = []

    def notify(self, event, text):
        self.events.append((event, text))


class EscalationTest(unittest.TestCase):
    def make(self, tmp, escalate_after=3):
        general = General(
            state_file=Path(tmp) / "state.json",
            escalate_after=escalate_after,
            # These tests model one failure per tick, so the post-failure cooldown
            # that protects a real deployment would only get in the way.
            failed_ping_cooldown=0.0,
        )
        config = Config(
            general=general,
            providers={"fake": ProviderConfig(name="fake")},
            telegram=TelegramConfig(enabled=True, bot_token="t", chat_id=1),
        )
        collector = Collector()
        return Watcher(config, collector), collector

    def test_three_failures_escalate_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher, collector = self.make(tmp)
            provider = FailingProvider(ok=False)
            for _ in range(3):
                watcher.tick([provider])
            kinds = [event for event, _ in collector.events]
            # One message per outage: the first failure and the escalation at the
            # threshold, not one message per failed tick.
            self.assertEqual(kinds.count(ERROR), 2)
            self.assertEqual(kinds.count(ESCALATE), 1)
            self.assertEqual(State(Path(tmp) / "state.json").provider("fake")["fail_streak"], 3)

    def test_escalation_repeats_at_the_next_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher, collector = self.make(tmp)
            provider = FailingProvider(ok=False)
            for _ in range(6):
                watcher.tick([provider])
            kinds = [event for event, _ in collector.events]
            self.assertEqual(kinds.count(ESCALATE), 2)

    def test_success_resets_the_streak(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher, _ = self.make(tmp)
            failing = FailingProvider(ok=False)
            watcher.tick([failing])
            watcher.tick([failing])
            self.assertEqual(State(Path(tmp) / "state.json").provider("fake")["fail_streak"], 2)
            watcher.tick([FailingProvider(ok=True)])
            self.assertEqual(State(Path(tmp) / "state.json").provider("fake")["fail_streak"], 0)

    def test_zero_disables_escalation(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher, collector = self.make(tmp, escalate_after=0)
            provider = FailingProvider(ok=False)
            for _ in range(4):
                watcher.tick([provider])
            self.assertNotIn(ESCALATE, [event for event, _ in collector.events])

    def test_escalation_message_is_localized(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher, collector = self.make(tmp, escalate_after=1)
            watcher.state.set_chat_lang(1, "ru")  # owner speaks Russian
            watcher.tick([FailingProvider(ok=False)])
            text = [t for e, t in collector.events if e == ESCALATE][0]
            self.assertIn("нужна помощь", text)  # owner language is ru in this fixture


if __name__ == "__main__":
    unittest.main()
