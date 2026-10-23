"""Provider interface: read usage (free) and trigger a window (tiny quota)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Window:
    """One rolling limit window."""

    pct: float | None = None          # used percent, 0..100
    reset_at: float | None = None     # epoch seconds, None when not started/known
    enforced: bool = True             # False when the provider dropped this limit
    exceeded: bool | None = None

    @property
    def active(self) -> bool:
        return self.reset_at is not None


@dataclass
class Usage:
    provider: str
    five: Window = field(default_factory=Window)
    weekly: Window = field(default_factory=Window)
    plan: str | None = None
    details: list[str] = field(default_factory=list)

    @property
    def weekly_exhausted(self) -> bool:
        return self.weekly.pct is not None and self.weekly.exceeded is True


@dataclass
class PingResult:
    ok: bool
    seconds: float = 0.0
    model: str | None = None
    tokens: int | None = None
    cost_usd: float | None = None
    detail: str | None = None
    error: str | None = None


class Provider(Protocol):
    name: str
    title: str

    def usage(self) -> Usage: ...

    def ping(self) -> PingResult: ...


def to_epoch(value) -> float | None:
    """Accept epoch seconds, epoch milliseconds, or an ISO-8601 string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0:
            return None
        return number / 1000.0 if number > 100_000_000_000 else number
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            try:
                return to_epoch(float(text))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.timestamp()
    return None


PROVIDER_TITLES = {
    "claude": "Claude Code",
    "codex": "Codex",
    "commandcode": "Command Code",
    "glm": "GLM Coding Plan",
    "kimi": "Kimi for Coding",
    "minimax": "MiniMax Coding Plan",
}
