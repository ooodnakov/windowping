"""The scheduling brain plus the long-running watcher loop."""

from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from .config import Config, General
from .providers.base import PingResult, Provider, Usage
from .render import (
    fmt_delta,
    fmt_ts,
    message_error,
    message_ping,
    message_ping_failed,
    message_recovered,
    message_weekly,
)
from .state import State

PING = "ping"
ERROR = "error"
WEEKLY = "weekly"
RECOVERED = "recovered"
STATUS = "status"


@dataclass
class Decision:
    action: str  # "ping" | "wait" | "skip-weekly" | "cooldown" | "awaiting" | "no-5h-window" | "pinged"
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

    def message_lang(self) -> str:
        """Notifications follow the owner's chat language (see TelegramConfig.lang)."""
        chat_id = self.config.telegram.chat_id
        return self.config.telegram.resolve_lang(self.state.chat_lang(chat_id))

    # -- one pass --------------------------------------------------------- #

    def tick(self, providers: list[Provider], *, dry_run: bool = False) -> list[TickResult]:
        now = time.time()
        results: list[TickResult] = []
        for provider in providers:
            entry = self.state.provider(provider.name)
            previous_status = entry.get("status")
            events: list[tuple[str, str]] = []
            try:
                usage = provider.usage()
            except Exception as exc:  # noqa: BLE001 - reported, never fatal
                self.log(f"[{provider.name}] usage error: {exc}")
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
            ping_result: PingResult | None = None
            if decision.action != previous_status and previous_status != ERROR:
                self.log(f"[{provider.name}] {decision.action}: {decision.reason}")

            if decision.action == "skip-weekly":
                key = f"{usage.weekly.reset_at}"
                if not self.state.already_notified(provider.name, WEEKLY, key):
                    self.state.mark_notified(provider.name, WEEKLY, key)
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
                ping_result = provider.ping()
                if ping_result.ok:
                    entry = self.state.update(
                        provider.name,
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
                    self.log(f"[{provider.name}] ✗ ping failed: {ping_result.error}")
                    self.state.update(
                        provider.name,
                        last_error=ping_result.error,
                        last_error_at=now,
                        last_ping_result={"ok": False, "error": ping_result.error},
                    )
                    events.append((ERROR, message_ping_failed(provider.title, ping_result.error, self.message_lang())))

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

        self.log(f"watching {', '.join(p.name for p in providers)} "
                 f"(every {self.config.general.tick_interval:.0f}s, "
                 f"buffer {self.config.general.reset_buffer:.0f}s)")
        while not stop.is_set():
            started = time.monotonic()
            try:
                self.tick(providers)
            except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the loop
                self.log(f"tick failed: {exc}")
            elapsed = time.monotonic() - started
            stop.wait(max(1.0, self.config.general.tick_interval - elapsed))

    def log(self, message: str) -> None:  # pragma: no cover - output only
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{stamp} {message}", flush=True)
