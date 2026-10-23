import datetime as dt
import tempfile
import unittest
from pathlib import Path

from windowping.config import Config, General, ProviderConfig, TelegramConfig
from windowping.providers.base import PingResult, Usage, Window
from windowping.state import State
from windowping.watcher import ERROR, PING, WEEKLY, Watcher, decide

NOW = 1_800_000_000.0


def general(**kwargs) -> General:
    state_file = kwargs.pop("state_file", Path(tempfile.gettempdir()) / "windowping-test-state.json")
    return General(
        weekly_threshold=float(kwargs.pop("weekly_threshold", 0.99)),
        reset_buffer=float(kwargs.pop("reset_buffer", 300.0)),
        cooldown=float(kwargs.pop("cooldown", 600.0)),
        register_grace=float(kwargs.pop("register_grace", 1800.0)),
        state_file=state_file,
    )


class DecideTest(unittest.TestCase):
    def test_no_active_window_pings(self):
        usage = Usage(provider="x", five=Window(pct=0, reset_at=None), weekly=Window(pct=10))
        decision = decide(usage, general(), {}, NOW)
        self.assertEqual(decision.action, "ping")

    def test_active_window_waits(self):
        usage = Usage(provider="x", five=Window(pct=5, reset_at=NOW + 3600), weekly=Window(pct=10))
        self.assertEqual(decide(usage, general(), {}, NOW).action, "wait")

    def test_past_reset_pings_after_buffer(self):
        usage = Usage(provider="x", five=Window(pct=100, reset_at=NOW - 600), weekly=Window(pct=10))
        self.assertEqual(decide(usage, general(), {}, NOW).action, "ping")

    def test_buffer_blocks_immediately_after_reset(self):
        usage = Usage(provider="x", five=Window(pct=100, reset_at=NOW - 60), weekly=Window(pct=10))
        self.assertEqual(decide(usage, general(), {}, NOW).action, "wait")

    def test_same_window_is_not_pinged_twice(self):
        reset = NOW - 600
        usage = Usage(provider="x", five=Window(pct=100, reset_at=reset), weekly=Window(pct=10))
        entry = {"pinged_for_reset": reset, "last_ping": NOW - 500}
        self.assertEqual(decide(usage, general(), entry, NOW).action, "pinged")

    def test_weekly_exhausted_wins(self):
        usage = Usage(
            provider="x",
            five=Window(pct=100, reset_at=NOW - 600),
            weekly=Window(pct=100, reset_at=NOW + 3600, exceeded=True),
        )
        self.assertEqual(decide(usage, general(), {}, NOW).action, "skip-weekly")

    def test_awaiting_registration(self):
        usage = Usage(provider="x", five=Window(pct=0, reset_at=None), weekly=Window(pct=10))
        entry = {"last_ping": NOW - 120}
        self.assertEqual(decide(usage, general(), entry, NOW).action, "awaiting")

    def test_cooldown(self):
        usage = Usage(provider="x", five=Window(pct=100, reset_at=NOW - 600), weekly=Window(pct=10))
        entry = {"last_ping": NOW - 60}
        self.assertEqual(decide(usage, general(), entry, NOW).action, "cooldown")

    def test_no_five_hour_limit(self):
        usage = Usage(provider="x", five=Window(enforced=False), weekly=Window(pct=10))
        self.assertEqual(decide(usage, general(), {}, NOW).action, "no-5h-window")


class FakeProvider:
    name = "fake"
    title = "Fake"

    def __init__(self, usage, ping_ok=True):
        self._usage = usage
        self.ping_ok = ping_ok
        self.pings = 0

    def usage(self):
        return self._usage

    def ping(self):
        self.pings += 1
        return PingResult(ok=self.ping_ok, seconds=1.0, model="m", tokens=7,
                          error=None if self.ping_ok else "boom")


class Collector:
    def __init__(self):
        self.events = []

    def notify(self, event, text):
        self.events.append((event, text))


class WatcherTest(unittest.TestCase):
    def make_config(self, tmp) -> Config:
        return Config(
            general=general(state_file=Path(tmp) / "state.json"),
            providers={"fake": ProviderConfig(name="fake")},
            telegram=TelegramConfig(),
        )

    def test_ping_happens_once_per_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=100, reset_at=1.0), weekly=Window(pct=1))
            provider = FakeProvider(usage)
            collector = Collector()
            watcher = Watcher(self.make_config(tmp), collector)

            first = watcher.tick([provider])
            self.assertEqual(provider.pings, 1)
            self.assertEqual([e for e, _ in first[0].events], [PING])

            # the same window must not be pinged again
            second = watcher.tick([provider])
            self.assertEqual(provider.pings, 1)
            decision = second[0].decision
            assert decision is not None
            self.assertEqual(decision.action, "pinged")

    def test_weekly_exhausted_notifies_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(
                provider="fake",
                five=Window(pct=100, reset_at=1.0),
                weekly=Window(pct=100, reset_at=2.0, exceeded=True),
            )
            provider = FakeProvider(usage)
            collector = Collector()
            watcher = Watcher(self.make_config(tmp), collector)
            watcher.tick([provider])
            watcher.tick([provider])
            self.assertEqual(provider.pings, 0)
            self.assertEqual([e for e, _ in collector.events], [WEEKLY])

    def test_usage_error_is_reported_and_state_marks_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Broken(FakeProvider):
                def usage(self):
                    raise RuntimeError("no key")

            config = self.make_config(tmp)
            provider = Broken(Usage(provider="fake"))
            collector = Collector()
            watcher = Watcher(config, collector)
            results = watcher.tick([provider])
            self.assertEqual(results[0].error, "no key")
            self.assertEqual([e for e, _ in collector.events], [ERROR])
            saved = State(Path(tmp) / "state.json").provider("fake")
            self.assertEqual(saved.get("status"), ERROR)

    def test_failed_ping_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            provider = FakeProvider(usage, ping_ok=False)
            collector = Collector()
            watcher = Watcher(self.make_config(tmp), collector)
            results = watcher.tick([provider])
            self.assertTrue(results[0].ping is not None)
            self.assertEqual([e for e, _ in collector.events], [ERROR])


class HistoryAndDigestTest(unittest.TestCase):
    def config(self, tmp, **telegram) -> Config:
        return Config(
            general=general(state_file=Path(tmp) / "state.json"),
            providers={"fake": ProviderConfig(name="fake")},
            telegram=TelegramConfig(**{"enabled": True, "bot_token": "t", "chat_id": 1, **telegram}),
        )

    def test_a_ping_is_recorded_in_the_event_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=100, reset_at=1.0), weekly=Window(pct=1))
            watcher = Watcher(self.config(tmp), Collector())
            watcher.tick([FakeProvider(usage)])
            events = watcher.history.events()
            self.assertEqual([e["event"] for e in events], ["ping"])
            self.assertEqual(events[0]["provider"], "fake")
            self.assertEqual(events[0]["tokens"], 7)

    def test_failure_and_usage_error_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            watcher = Watcher(self.config(tmp), Collector())
            watcher.tick([FakeProvider(usage, ping_ok=False)])

            class Broken(FakeProvider):
                def usage(self):
                    raise RuntimeError("no key")

            watcher.tick([Broken(usage)])
            kinds = [e["event"] for e in watcher.history.events()]
            self.assertEqual(kinds, ["ping_failed", "error"])

    def test_digest_waits_for_its_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher = Watcher(self.config(tmp, digest_at="08:00"), Collector())
            morning = dt.datetime(2026, 10, 22, 8, 0).timestamp()
            earlier = dt.datetime(2026, 10, 22, 7, 59).timestamp()
            self.assertIsNone(watcher.maybe_digest(now=earlier))
            digest = watcher.maybe_digest(now=morning)
            self.assertIsNotNone(digest)
            assert digest is not None
            self.assertEqual(digest[0], "digest")
            self.assertIn("стат", digest[1].lower() + "стат")  # localized, never empty

    def test_digest_is_sent_once_a_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher = Watcher(self.config(tmp, digest_at="08:00"), Collector())
            first = dt.datetime(2026, 10, 22, 8, 0).timestamp()
            later = dt.datetime(2026, 10, 22, 23, 0).timestamp()
            tomorrow = dt.datetime(2026, 10, 23, 8, 0).timestamp()
            self.assertIsNotNone(watcher.maybe_digest(now=first))
            self.assertIsNone(watcher.maybe_digest(now=later))
            self.assertIsNotNone(watcher.maybe_digest(now=tomorrow))

    def test_digest_is_off_by_default_and_needs_telegram(self):
        with tempfile.TemporaryDirectory() as tmp:
            off = Watcher(self.config(tmp), Collector())
            self.assertIsNone(off.maybe_digest(now=dt.datetime(2026, 10, 22, 9, 0).timestamp()))

    def test_broken_digest_time_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher = Watcher(self.config(tmp, digest_at="eight"), Collector())
            self.assertIsNone(watcher.maybe_digest(now=dt.datetime(2026, 10, 22, 9, 0).timestamp()))


if __name__ == "__main__":
    unittest.main()
