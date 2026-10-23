import json
import tempfile
import time
import unittest
from pathlib import Path

from windowping.history import History, Stats, ProviderStats


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"
        self.history = History(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_appends_one_json_line_per_event(self):
        self.history.record("ping", provider="codex", tokens=16)
        self.history.record("ping", provider="glm", tokens=14)
        lines = self.path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["event"], "ping")
        self.assertEqual(first["provider"], "codex")
        self.assertEqual(first["tokens"], 16)
        self.assertIn("ts", first)

    def test_none_fields_are_dropped(self):
        self.history.record("ping", provider="codex", tokens=None, model="m")
        entry = json.loads(self.path.read_text().splitlines()[0])
        self.assertNotIn("tokens", entry)
        self.assertEqual(entry["model"], "m")

    def test_missing_directory_is_created(self):
        deep = History(Path(self.tmp.name) / "a" / "b" / "events.jsonl")
        deep.record("ping", provider="x")
        self.assertTrue(deep.path.exists())

    def test_unwritable_path_does_not_raise(self):
        blocked = History(Path(self.tmp.name))  # a directory, not a file
        blocked.record("ping", provider="x")  # must not raise


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"
        self.history = History(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_torn_lines_are_skipped(self):
        self.path.write_text(
            '{"ts": 1000, "event": "ping", "provider": "codex", "tokens": 16}\n'
            '{"ts": 1001, "event": "pi\n'
            'not json at all\n'
            '{"ts": 1002, "event": "ping", "provider": "glm"}\n'
        )
        events = self.history.events()
        self.assertEqual([e["ts"] for e in events], [1000, 1002])

    def test_since_and_until_filter(self):
        for ts in (100, 200, 300):
            with self.path.open("a") as handle:
                handle.write(json.dumps({"ts": ts, "event": "ping"}) + "\n")
        self.assertEqual([e["ts"] for e in self.history.events(since=150)], [200, 300])
        self.assertEqual([e["ts"] for e in self.history.events(since=0, until=250)], [100, 200])

    def test_missing_file_is_empty(self):
        self.assertEqual(self.history.events(), [])


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history = History(Path(self.tmp.name) / "events.jsonl")
        now = time.time()
        self.now = now
        rows = [
            {"ts": now - 60, "event": "ping", "provider": "codex", "tokens": 16, "seconds": 1.9},
            {"ts": now - 50, "event": "ping", "provider": "codex", "tokens": 16, "seconds": 2.1},
            {"ts": now - 40, "event": "ping", "provider": "glm", "tokens": 14, "seconds": 1.5},
            {"ts": now - 30, "event": "ping_failed", "provider": "glm", "error": "boom"},
            {"ts": now - 20, "event": "weekly", "provider": "glm"},
            {"ts": now - 10, "event": "error", "provider": "codex", "error": "dns"},
            {"ts": now - 10 * 86400, "event": "ping", "provider": "codex", "tokens": 99},
        ]
        with self.history.path.open("a") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_aggregates_within_the_window(self):
        stats = self.history.stats(days=1, now=self.now)
        self.assertEqual(stats.pings, 3)
        self.assertEqual(stats.failures, 1)
        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.weekly_stops, 1)
        self.assertEqual(stats.tokens, 46)
        self.assertAlmostEqual(stats.seconds, 5.5)
        self.assertEqual(stats.providers["codex"].pings, 2)
        self.assertEqual(stats.providers["codex"].tokens, 32)
        self.assertEqual(stats.providers["glm"].failures, 1)
        self.assertEqual(stats.days, 1)

    def test_old_events_fall_out_of_the_window(self):
        self.assertEqual(self.history.stats(days=1, now=self.now).pings, 3)
        self.assertEqual(self.history.stats(days=30, now=self.now).pings, 4)

    def test_coverage_is_five_hours_per_ping(self):
        stats = self.history.stats(days=1, now=self.now)
        self.assertAlmostEqual(stats.coverage_hours, 15.0)

    def test_empty_stats(self):
        empty = History(Path(self.tmp.name) / "nothing.jsonl").stats(days=7)
        self.assertEqual(empty.pings, 0)
        self.assertFalse(empty.ok)
        self.assertIsInstance(empty, Stats)
        self.assertIsInstance(empty.providers, dict)
        self.assertIsInstance(ProviderStats(), ProviderStats)


class TrimTest(unittest.TestCase):
    def test_old_lines_are_dropped_and_recent_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = History(Path(tmp) / "events.jsonl")
            now = time.time()
            with history.path.open("a") as handle:
                handle.write(json.dumps({"ts": now - 200 * 86400, "event": "ping"}) + "\n")
                handle.write(json.dumps({"ts": now - 86400, "event": "ping"}) + "\n")
            self.assertEqual(history.trim(keep_days=120, now=now), 1)
            self.assertEqual(len(history.events()), 1)

    def test_trim_keeps_unparseable_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = History(Path(tmp) / "events.jsonl")
            history.path.write_text("{broken\n")
            self.assertEqual(history.trim(keep_days=1), 0)
            self.assertEqual(history.path.read_text(), "{broken\n")


if __name__ == "__main__":
    unittest.main()
