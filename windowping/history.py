"""Append-only event log, and the numbers derived from it.

The state file answers "what is true right now"; nobody can answer "was this
worth running" from it. Every ping, failure and weekly stop is appended here as
one JSON line, so ``windowping stats`` can report what the daemon actually did
over a period without keeping a database.

The log is deliberately dumb: no locking beyond a single ``append``, no schema
version, one line per event. A corrupt line is skipped, never fatal.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

WINDOW_SECONDS = 5 * 3600.0  # a successful ping buys one 5-hour window


@dataclass
class ProviderStats:
    pings: int = 0
    failures: int = 0
    tokens: int = 0
    seconds: float = 0.0
    last_ping: float | None = None


@dataclass
class Stats:
    days: int
    since: float
    until: float
    pings: int = 0
    failures: int = 0
    errors: int = 0
    weekly_stops: int = 0
    tokens: int = 0
    seconds: float = 0.0
    first_ping: float | None = None
    last_ping: float | None = None
    providers: dict[str, ProviderStats] = field(default_factory=dict)

    @property
    def coverage_hours(self) -> float:
        """Roughly how many hours of quota windows the pings opened."""
        return self.pings * WINDOW_SECONDS / 3600.0

    @property
    def ok(self) -> bool:
        return self.pings > 0


def default_path(state_file: Path) -> Path:
    return Path(state_file).with_name("events.jsonl")


class History:
    def __init__(self, path: Path):
        self.path = Path(path)

    # -- writing ---------------------------------------------------------- #

    def record(self, event: str, provider: str = "", **fields: object) -> None:
        # No rounding: a rounded-up timestamp can land a fraction of a
        # millisecond in the future and be filtered out by the very next read.
        entry: dict[str, object] = {"ts": time.time(), "event": event}
        if provider:
            entry["provider"] = provider
        entry.update({key: value for key, value in fields.items() if value is not None})
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        except OSError:
            # Losing an analytics line must never break a ping.
            pass

    # -- reading ---------------------------------------------------------- #

    def events(self, since: float = 0.0, until: float | None = None) -> list[dict]:
        until = time.time() if until is None else until
        out: list[dict] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue  # truncated write, a torn line, anything
                    if not isinstance(entry, dict):
                        continue
                    ts = entry.get("ts")
                    if not isinstance(ts, (int, float)):
                        continue
                    if since <= ts <= until + 1e-3:
                        out.append(entry)
        except FileNotFoundError:
            return []
        except OSError:
            return out
        return out

    def stats(self, days: int = 7, now: float | None = None) -> Stats:
        now = time.time() if now is None else now
        since = now - days * 86400.0
        stats = Stats(days=days, since=since, until=now)
        for entry in self.events(since, now):
            event = entry.get("event")
            provider = str(entry.get("provider") or "")
            bucket = stats.providers.setdefault(provider, ProviderStats()) if provider else None
            if event == "ping":
                stats.pings += 1
                tokens = entry.get("tokens")
                seconds = entry.get("seconds")
                if isinstance(tokens, int):
                    stats.tokens += tokens
                    if bucket:
                        bucket.tokens += tokens
                if isinstance(seconds, (int, float)):
                    stats.seconds += float(seconds)
                    if bucket:
                        bucket.seconds += float(seconds)
                ts = entry.get("ts")
                if isinstance(ts, (int, float)):
                    if stats.first_ping is None or ts < stats.first_ping:
                        stats.first_ping = ts
                    if stats.last_ping is None or ts > stats.last_ping:
                        stats.last_ping = ts
                if bucket:
                    bucket.pings += 1
                    bucket.last_ping = entry.get("ts") if isinstance(entry.get("ts"), (int, float)) else None
            elif event == "ping_failed":
                stats.failures += 1
                if bucket:
                    bucket.failures += 1
            elif event == "error":
                stats.errors += 1
            elif event == "weekly":
                stats.weekly_stops += 1
        return stats

    # -- maintenance ------------------------------------------------------ #

    def trim(self, keep_days: int = 120, now: float | None = None) -> int:
        """Drop events older than ``keep_days``. Returns how many lines went away."""
        now = time.time() if now is None else now
        cutoff = now - keep_days * 86400.0
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        kept: list[str] = []
        dropped = 0
        for line in lines:
            try:
                entry = json.loads(line)
                ts = entry.get("ts") if isinstance(entry, dict) else None
            except ValueError:
                ts = None
            if isinstance(ts, (int, float)) and ts < cutoff:
                dropped += 1
                continue
            kept.append(line)
        if dropped:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            os.replace(tmp, self.path)
        return dropped
