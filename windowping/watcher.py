"""The scheduling brain plus the long-running watcher loop."""

from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import datetime as dt

from .config import Config, General
from .history import History, default_path
from .providers.base import PingResult, Provider, Usage
from . import errors, sdnotify
from .render import (
    fmt_delta,
    fmt_ts,
    message_error,
    message_escalate,
    message_ping,
    message_ping_failed,
    message_recovered,
    message_weekly,
    telegram_stats,
)
from .schedule import Schedule
from .state import State

PING = "ping"
ERROR = "error"
WEEKLY = "weekly"
RECOVERED = "recovered"
ESCALATE = "escalate"
STATUS = "status"


@dataclass
class Decision:
    # "ping" | "wait" | "skip-weekly" | "cooldown" | "awaiting" | "no-5h-window"
    # | "pinged" | "scheduled-off"
    action: str
    reason: str


def decide(usage: Usage, general: General, entry: dict, now: float | None = None) -> Decision:
    """Decide what to do for one provider right now.

    Order matters: an exhausted weekly meter makes every 5h ping pointless, and
    a ping that has not appeared in the usage meter yet must not be repeated.
    """
    now = now if now is not None else time.time()
    five, weekly = usage.five, usage.weekly

    if weekly.pct is not None and weekly.pct >= general.weekly_percent:
        return Decision(
            "skip-weekly",
            f"weekly {weekly.pct:.0f}% used, resets {fmt_ts(weekly.reset_at)}",
        )

    if not five.enforced:
        return Decision("no-5h-window", "provider does not enforce a 5h limit")

    last_ping = float(entry.get("last_ping") or 0)
    if five.reset_at is None:
        if last_ping and now - last_ping < general.register_grace:
            return Decision(
                "awaiting",
                f"pinged {fmt_delta(now - last_ping)} ago, waiting for the window to register",
            )
        return Decision("ping", "no 5h window active")

    if now < five.reset_at + general.reset_buffer:
        return Decision(
            "wait",
            f"5h window active ({five.pct:.0f}%), resets in {fmt_delta(five.reset_at - now)}",
        )

    if entry.get("pinged_for_reset") == five.reset_at:
        return Decision("pinged", "already pinged for this window")
    if last_ping and now - last_ping < general.cooldown:
        return Decision("cooldown", f"cooldown ({fmt_delta(now - last_ping)} since last ping)")
    return Decision("ping", f"5h window reset at {fmt_ts(five.reset_at)}")


class Notifier(Protocol):
    """Anything with a ``notify`` method; the Telegram transport implements it."""

    def notify(self, event: str, text: str) -> None: ...


class NullNotifier:
    """Sink used when Telegram is disabled."""

    def notify(self, event: str, text: str) -> None:
        return


@dataclass
class TickResult:
    provider: str
    usage: Usage | None
    error: str | None
    decision: Decision | None
    ping: PingResult | None
    events: list[tuple[str, str]]


class Watcher:
    def __init__(self, config: Config, notifier: Notifier | None = None):
        self.config = config
        self.notifier = notifier or NullNotifier()
        self.state = State(config.general.state_file)
        self.history = History(
            config.general.history_file or default_path(config.general.state_file)
        )

    def message_lang(self) -> str:
        """Notifications follow the owner's chat language (see TelegramConfig.lang)."""
        chat_id = self.config.telegram.chat_id
        return self.config.telegram.resolve_lang(self.state.chat_lang(chat_id))

    @staticmethod
    def provider_schedule(provider: Provider) -> Schedule | None:
        """The provider's own schedule, if the config gave it one."""
        cfg = getattr(provider, "cfg", None)
        if cfg is None:
            return None
        try:
            return cfg.schedule()
        except ValueError:
            return None  # load() already rejected malformed specs

    def _read_usage(self, provider: Provider):
        """``usage()`` with a couple of retries: a read is free, a lost tick is not."""
        attempts = 1 + max(0, int(self.config.general.read_retries))
        delay = self.config.general.retry_delay
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                return provider.usage(), None
            except Exception as exc:  # noqa: BLE001 - reported by the caller
                last = exc
                if attempt + 1 < attempts and errors.is_network(str(exc)):
                    self.log(f"[{provider.name}] usage read failed ({exc}); retrying in {delay:.0f}s")
                    time.sleep(delay)
                    delay *= 2
                else:
                    break
        return None, last

    def _ping_with_retries(self, provider: Provider):
        """Ping, retrying only when the failure looks like a connection problem."""
        attempts = 1 + max(0, int(self.config.general.ping_retries))
        delay = self.config.general.retry_delay
        result = None
        for attempt in range(attempts):
            result = provider.ping()
            if result.ok:
                return result
            if attempt + 1 < attempts and errors.is_network(result.error):
                self.log(
                    f"[{provider.name}] ✗ ping failed ({result.error}); "
                    f"retry {attempt + 1}/{attempts - 1} in {delay:.0f}s"
                )
                time.sleep(delay)
                delay *= 2
            else:
                return result
        return result

    # -- one pass --------------------------------------------------------- #

    def tick(self, providers: list[Provider], *, dry_run: bool = False) -> list[TickResult]:
        now = time.time()
        results: list[TickResult] = []
        for provider in providers:
            entry = self.state.provider(provider.name)
            previous_status = entry.get("status")
            events: list[tuple[str, str]] = []
            usage, read_error = self._read_usage(provider)
            if usage is None:
                exc = read_error or RuntimeError("usage unavailable")
                self.log(f"[{provider.name}] usage error: {exc}")
                self.history.record(
                    "error", provider=provider.name, error=str(exc), kind=errors.classify(str(exc))
                )
                self.state.update(provider.name, status=ERROR, last_error=str(exc), last_error_at=now)
                if not self.state.already_notified(provider.name, ERROR, ERROR):
                    self.state.mark_notified(provider.name, ERROR, ERROR)
                    events.append((ERROR, message_error(provider.title, str(exc), self.message_lang())))
                results.append(TickResult(provider.name, None, str(exc), None, None, events))
                self.state.save()
                for event, text in events:
                    self.notifier.notify(event, text)
                continue

            if entry.get("status") == ERROR:
                notified = dict(entry.get("notified") or {})
                notified["error"] = None  # a future failure should be reported again
                entry["notified"] = notified
                events.append((RECOVERED, message_recovered(provider.title, self.message_lang())))

            decision = decide(usage, self.config.general, entry, now)
            schedule = self.provider_schedule(provider)
            if decision.action == "ping" and schedule is not None:
                moment = dt.datetime.fromtimestamp(now)
                if not schedule.allows(moment):
                    upcoming = schedule.next_open(moment)
                    when = (
                        fmt_ts(upcoming.timestamp()) if upcoming is not None else "never"
                    )
                    decision = Decision(
                        "scheduled-off",
                        f"outside schedule ({schedule.describe()}), next ping after {when}",
                    )
            ping_result: PingResult | None = None
            if decision.action != previous_status and previous_status != ERROR:
                self.log(f"[{provider.name}] {decision.action}: {decision.reason}")

            if decision.action == "skip-weekly":
                key = f"{usage.weekly.reset_at}"
                if not self.state.already_notified(provider.name, WEEKLY, key):
                    self.state.mark_notified(provider.name, WEEKLY, key)
                    self.history.record("weekly", provider=provider.name, reset_at=usage.weekly.reset_at)
                    events.append(
                        (
                            WEEKLY,
                            message_weekly(
                                provider.title,
                                usage.weekly.pct,
                                usage.weekly.reset_at,
                                now,
                                self.message_lang(),
                            ),
                        )
                    )

            elif decision.action == "ping" and not dry_run:
                prior_streak = int(entry.get("fail_streak") or 0)
                ping_result = self._ping_with_retries(provider)
                if ping_result.ok:
                    entry = self.state.update(
                        provider.name,
                        fail_streak=0,
                        last_ping=now,
                        pinged_for_reset=usage.five.reset_at,
                        last_ping_result={
                            "ok": True,
                            "model": ping_result.model,
                            "tokens": ping_result.tokens,
                            "seconds": round(ping_result.seconds, 1),
                        },
                    )
                    entry.pop("last_error", None)
                    bits = []
                    if ping_result.seconds:
                        bits.append(f"{ping_result.seconds:.1f}s")
                    if ping_result.tokens:
                        bits.append(f"{ping_result.tokens} tokens")
                    suffix = f" ({', '.join(bits)})" if bits else ""
                    self.log(f"[{provider.name}] ✓ pinged{suffix} {ping_result.model or ''}".rstrip())
                    # A free re-read tells the message when the new window ends.
                    probe_reset = None
                    try:
                        probe_reset = provider.usage().five.reset_at
                    except Exception:  # noqa: BLE001 - cosmetic only
                        probe_reset = None
                    self.history.record(
                        "ping",
                        provider=provider.name,
                        model=ping_result.model,
                        tokens=ping_result.tokens,
                        seconds=round(ping_result.seconds, 3) if ping_result.seconds else None,
                        reset_at=probe_reset,
                        mode=ping_result.detail,
                    )
                    if prior_streak > 0:
                        events.append((RECOVERED, message_recovered(provider.title, self.message_lang())))
                    events.append(
                        (
                            PING,
                            message_ping(
                                provider.title,
                                ping_result.model,
                                ping_result.tokens,
                                ping_result.seconds,
                                decision.reason,
                                reset_at=probe_reset,
                                lang=self.message_lang(),
                            ),
                        )
                    )
                else:
                    kind = errors.classify(ping_result.error)
                    self.log(f"[{provider.name}] ✗ ping failed ({kind or 'unknown'}): {ping_result.error}")
                    self.history.record(
                        "ping_failed",
                        provider=provider.name,
                        error=ping_result.error,
                        kind=kind,
                    )
                    self.state.update(
                        provider.name,
                        last_error=ping_result.error,
                        last_error_at=now,
                        last_ping_result={"ok": False, "error": ping_result.error, "kind": kind},
                    )
                    streak = int(entry.get("fail_streak") or 0) + 1
                    self.state.update(provider.name, fail_streak=streak)
                    limit = self.config.general.escalate_after
                    escalating = limit > 0 and streak % limit == 0
                    # One message per outage, not one per tick: the first failure is
                    # news, the next nine are the same news. Escalation still repeats
                    # every `escalate_after` failures, so a long outage cannot hide.
                    notify = streak == 1 or escalating
                    if notify and kind == "network":
                        # The whole tunnel fails at once, so one "network is down"
                        # message covers every provider in this incident.
                        last = float(self.state.data.get("network_notified_at") or 0)
                        if now - last < self.config.general.network_notify_cooldown:
                            notify = False
                        else:
                            self.state.data["network_notified_at"] = now
                    if notify:
                        events.append(
                            (ERROR, message_ping_failed(provider.title, ping_result.error, self.message_lang()))
                        )
                    if escalating:
                        self.log(f"[{provider.name}] {streak} failed pings in a row, escalating")
                        events.append(
                            (
                                ESCALATE,
                                message_escalate(
                                    provider.title, streak, ping_result.error, self.message_lang()
                                ),
                            )
                        )

            self.state.update(
                provider.name,
                status=decision.action,
                decision=decision.reason,
                checked_at=now,
            )
            results.append(TickResult(provider.name, usage, None, decision, ping_result, events))
            self.state.save()

            for event, text in events:
                self.notifier.notify(event, text)

        return results

    # -- daily digest ----------------------------------------------------- #

    def maybe_digest(self, now: float | None = None) -> tuple[str, str] | None:
        """One short summary per day, sent after ``[telegram] digest_at`` (local)."""
        at = (self.config.telegram.digest_at or "").strip()
        if not at or not self.config.telegram.enabled:
            return None
        try:
            hour, minute = (int(part) for part in at.split(":", 1))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            self.log(f"ignoring digest_at={at!r}, expected HH:MM")
            return None
        moment = dt.datetime.fromtimestamp(now if now is not None else time.time())
        if (moment.hour, moment.minute) < (hour, minute):
            return None
        today = moment.strftime("%Y-%m-%d")
        if self.state.data.get("digest_sent") == today:
            return None
        self.state.data["digest_sent"] = today
        self.state.save()
        stats = self.history.stats(days=1, now=now)
        return ("digest", telegram_stats(stats, self.message_lang(), digest=True))

    # -- loop ------------------------------------------------------------- #

    def run_forever(self, providers: list[Provider], stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()

        def _stop(signum, frame):  # pragma: no cover - signal path
            stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _stop)
            except ValueError:
                pass

        self.history.trim(120)
        sdnotify.ready()
        self.log(f"watching {', '.join(p.name for p in providers)} "
                 f"(every {self.config.general.tick_interval:.0f}s, "
                 f"buffer {self.config.general.reset_buffer:.0f}s)")
        while not stop.is_set():
            started = time.monotonic()
            try:
                self.tick(providers)
            except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the loop
                self.log(f"tick failed: {exc}")
            try:
                digest = self.maybe_digest()
                if digest:
                    self.notifier.notify(*digest)
            except Exception as exc:  # noqa: BLE001 - the digest is never worth a crash
                self.log(f"digest failed: {exc}")
            # Type=notify + WatchdogSec: a hung tick gets the unit restarted.
            sdnotify.watchdog()
            elapsed = time.monotonic() - started
            stop.wait(max(1.0, self.config.general.tick_interval - elapsed))
        sdnotify.stopping()

    def log(self, message: str) -> None:  # pragma: no cover - output only
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{stamp} {message}", flush=True)
