import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from windowping import errors
from windowping.config import Config, General, ProviderConfig, TelegramConfig
from windowping.providers.base import PingResult, Usage, Window
from windowping.schedule import Schedule, parse
from windowping.watcher import ERROR, ESCALATE, PING, RECOVERED, Watcher

# 2026-10-24 is a Saturday; 2026-10-26 is the following Monday.
SATURDAY_NOON = dt.datetime(2026, 10, 24, 12, 0)
MONDAY_MORNING = dt.datetime(2026, 10, 26, 9, 0)


class ParseTest(unittest.TestCase):
    def test_always_is_none(self):
        for spec in (None, "", "always", "*", "any", "ALWAYS"):
            self.assertIsNone(parse(spec), spec)

    def test_never_matches_nothing(self):
        schedule = parse("never")
        self.assertIsNotNone(schedule)
        assert schedule is not None
        self.assertFalse(schedule.allows(SATURDAY_NOON))
        self.assertFalse(schedule.allows(MONDAY_MORNING))
        self.assertIsNone(schedule.next_open(SATURDAY_NOON))

    def test_weekdays_only(self):
        schedule = parse("mon-fri")
        assert schedule is not None
        self.assertTrue(schedule.allows(MONDAY_MORNING))
        self.assertFalse(schedule.allows(SATURDAY_NOON))
        self.assertEqual(schedule.next_open(SATURDAY_NOON), dt.datetime(2026, 10, 26, 0, 0))

    def test_window_and_days(self):
        schedule = parse("mon-fri 07:00-23:30")
        assert schedule is not None
        self.assertTrue(schedule.allows(dt.datetime(2026, 10, 26, 7, 0)))
        self.assertTrue(schedule.allows(dt.datetime(2026, 10, 26, 23, 29)))
        self.assertFalse(schedule.allows(dt.datetime(2026, 10, 26, 23, 30)))
        self.assertFalse(schedule.allows(dt.datetime(2026, 10, 26, 6, 59)))
        self.assertEqual(schedule.describe(), "mon-fri 07:00-23:30")

    def test_window_that_wraps_midnight(self):
        schedule = parse("weekends 22:00-02:00")
        assert schedule is not None
        self.assertTrue(schedule.allows(dt.datetime(2026, 10, 24, 23, 0)))   # Saturday evening
        self.assertTrue(schedule.allows(dt.datetime(2026, 10, 25, 1, 30)))   # Sunday early
        self.assertFalse(schedule.allows(dt.datetime(2026, 10, 25, 3, 0)))
        # 01:00 Monday is still Sunday's window (Sunday is allowed), so it counts.
        self.assertTrue(schedule.allows(dt.datetime(2026, 10, 26, 1, 0)))
        # Tuesday 01:00 would belong to Monday, which is not in "weekends".
        self.assertFalse(schedule.allows(dt.datetime(2026, 10, 27, 1, 0)))

    def test_wrapping_window_not_allowed_when_previous_day_is_off(self):
        schedule = parse("mon 22:00-02:00")
        assert schedule is not None
        self.assertTrue(schedule.allows(dt.datetime(2026, 10, 26, 23, 0)))
        self.assertTrue(schedule.allows(dt.datetime(2026, 10, 27, 1, 0)))   # Monday's window
        self.assertFalse(schedule.allows(dt.datetime(2026, 10, 28, 1, 0)))  # Tuesday 01:00, Monday long over

    def test_lists_and_wrapping_ranges(self):
        schedule = parse("mon,wed,fri")
        assert schedule is not None
        self.assertEqual(schedule.describe(), "mon,wed,fri")
        weekend = parse("fri-mon")
        assert weekend is not None
        self.assertEqual(sorted(weekend.days), [0, 4, 5, 6])

    def test_aliases(self):
        assert parse("weekdays") is not None
        self.assertEqual(parse("weekdays").describe(), "mon-fri")
        self.assertEqual(parse("weekends").describe(), "weekends")
        self.assertEqual(parse("daily").describe(), "every day")

    def test_bad_specs_are_rejected(self):
        for spec in ("mon-bla", "25:00-26:00", "mon-fri 07:00-07:00", "mon-fri tuesday", "mon-fri 7-23"):
            with self.assertRaises(ValueError, msg=spec):
                parse(spec)


class ClassificationTest(unittest.TestCase):
    def test_connection_failures_are_network(self):
        for message in (
            "network error: [Errno 104] Connection reset by peer",
            "network error: [Errno -2] Name or service not known",
            "network error: _ssl.c:983: The handshake operation timed out",
            "Remote end closed connection without response",
            "network error: timed out",
        ):
            self.assertEqual(errors.classify(message), "network", message)

    def test_answers_are_provider(self):
        self.assertEqual(errors.classify("HTTP 401: unauthorized"), "provider")
        self.assertEqual(errors.classify("no apiKey in /home/x/auth.json"), "provider")
        self.assertIsNone(errors.classify(None))


class FakeProvider:
    name = "fake"
    title = "Fake"

    def __init__(self, usage, ping_errors=None, cfg=None):
        self._usage = usage
        self.pings = 0
        self.ping_errors = list(ping_errors or [])
        self.cfg = cfg

    def usage(self):
        return self._usage

    def ping(self):
        self.pings += 1
        if self.ping_errors:
            return PingResult(ok=False, error=self.ping_errors.pop(0))
        return PingResult(ok=True, seconds=1.0, model="m", tokens=7)


class Collector:
    def __init__(self):
        self.events = []

    def notify(self, event, text):
        self.events.append((event, text))

    def kinds(self):
        return [event for event, _ in self.events]


def make_general(tmp, **kwargs) -> General:
    return General(
        state_file=Path(tmp) / "state.json",
        retry_delay=0.0,
        **kwargs,
    )


def make_config(tmp, general=None, schedule=None) -> Config:
    options = {"schedule": schedule} if schedule is not None else {}
    return Config(
        general=general or make_general(tmp),
        providers={"fake": ProviderConfig(name="fake", options=options)},
        telegram=TelegramConfig(),
    )


class ScheduleGateTest(unittest.TestCase):
    def test_outside_schedule_does_not_ping(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=100, reset_at=1.0), weekly=Window(pct=1))
            provider = FakeProvider(usage, cfg=ProviderConfig(name="fake", options={"schedule": "mon-fri"}))
            collector = Collector()
            watcher = Watcher(make_config(tmp, schedule="mon-fri"), collector)
            with mock.patch("windowping.watcher.time.time", return_value=SATURDAY_NOON.timestamp()):
                results = watcher.tick([provider])
            self.assertEqual(provider.pings, 0)
            self.assertEqual(results[0].decision.action, "scheduled-off")
            self.assertIn("mon-fri", results[0].decision.reason)
            self.assertEqual(collector.kinds(), [])

    def test_inside_schedule_pings(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=100, reset_at=1.0), weekly=Window(pct=1))
            provider = FakeProvider(usage, cfg=ProviderConfig(name="fake", options={"schedule": "mon-fri"}))
            watcher = Watcher(make_config(tmp, schedule="mon-fri"), Collector())
            with mock.patch("windowping.watcher.time.time", return_value=MONDAY_MORNING.timestamp()):
                watcher.tick([provider])
            self.assertEqual(provider.pings, 1)

    def test_usage_is_still_read_while_off_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=42, reset_at=1.0), weekly=Window(pct=10))
            provider = FakeProvider(usage, cfg=ProviderConfig(name="fake", options={"schedule": "never"}))
            watcher = Watcher(make_config(tmp, schedule="never"), Collector())
            results = watcher.tick([provider])
            self.assertIsNotNone(results[0].usage)
            self.assertEqual(provider.pings, 0)


class RetryTest(unittest.TestCase):
    def test_network_failures_are_retried_inside_the_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            provider = FakeProvider(
                usage,
                ping_errors=["network error: [Errno 104] Connection reset by peer", "network error: timed out"],
            )
            collector = Collector()
            general = make_general(tmp, ping_retries=2)
            watcher = Watcher(make_config(tmp, general=general), collector)
            results = watcher.tick([provider])
            self.assertEqual(provider.pings, 3)          # first + two retries
            self.assertTrue(results[0].ping.ok)          # the third attempt worked
            self.assertIn(PING, collector.kinds())

    def test_provider_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            provider = FakeProvider(usage, ping_errors=["HTTP 401: unauthorized", "HTTP 401: unauthorized"])
            watcher = Watcher(make_config(tmp, general=make_general(tmp, ping_retries=2)), Collector())
            watcher.tick([provider])
            self.assertEqual(provider.pings, 1)

    def test_retries_stop_when_attempts_run_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            provider = FakeProvider(usage, ping_errors=["network error: timed out"] * 5)
            watcher = Watcher(make_config(tmp, general=make_general(tmp, ping_retries=1)), Collector())
            watcher.tick([provider])
            self.assertEqual(provider.pings, 2)


class NotificationPolicyTest(unittest.TestCase):
    def test_one_message_per_outage_not_one_per_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            provider = FakeProvider(usage, ping_errors=["HTTP 401: unauthorized"] * 5)
            collector = Collector()
            general = make_general(tmp, ping_retries=0, escalate_after=3)
            watcher = Watcher(make_config(tmp, general=general), collector)
            watcher.tick([provider])
            watcher.tick([provider])
            self.assertEqual(collector.kinds(), [ERROR])              # only the first failure
            watcher.tick([provider])                                  # streak 3 -> escalate
            self.assertEqual(collector.kinds(), [ERROR, ERROR, ESCALATE])

    def test_recovery_is_announced(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            provider = FakeProvider(usage, ping_errors=["HTTP 500: nope"])
            collector = Collector()
            watcher = Watcher(make_config(tmp, general=make_general(tmp, ping_retries=0)), collector)
            watcher.tick([provider])
            watcher.tick([provider])       # now succeeds
            self.assertEqual(collector.kinds(), [ERROR, RECOVERED, PING])


class NetworkQuietTest(unittest.TestCase):
    def test_one_network_message_per_incident_across_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            first = FakeProvider(usage, ping_errors=["network error: [Errno 104] Connection reset by peer"])
            second = FakeProvider(usage, ping_errors=["network error: [Errno 104] Connection reset by peer"])
            second.name, second.title = "fake2", "Fake2"
            collector = Collector()
            general = make_general(tmp, ping_retries=0, network_notify_cooldown=1800)
            watcher = Watcher(make_config(tmp, general=general), collector)
            with mock.patch("windowping.watcher.time.time", return_value=SATURDAY_NOON.timestamp()):
                watcher.tick([first, second])
            self.assertEqual(collector.kinds(), [ERROR])   # one message, not two

    def test_provider_errors_are_not_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Usage(provider="fake", five=Window(pct=0), weekly=Window(pct=1))
            first = FakeProvider(usage, ping_errors=["HTTP 401: unauthorized"])
            second = FakeProvider(usage, ping_errors=["HTTP 401: unauthorized"])
            second.name, second.title = "fake2", "Fake2"
            collector = Collector()
            general = make_general(tmp, ping_retries=0, network_notify_cooldown=1800)
            watcher = Watcher(make_config(tmp, general=general), collector)
            watcher.tick([first, second])
            # A rejected key is per-account news, so both providers speak up.
            self.assertEqual(collector.kinds(), [ERROR, ERROR])


class ConfigValidationTest(unittest.TestCase):
    def test_bad_schedule_fails_at_load(self):
        from windowping.config import load

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '[general]\nstate_file = "' + tmp + '/state.json"\n'
                '[providers.glm]\nenabled = true\nschedule = "mon-fri 25:00-26:00"\n'
            )
            with self.assertRaises(ValueError) as ctx:
                load(path)
            self.assertIn("providers.glm.schedule", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
