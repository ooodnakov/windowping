"""Provider interface: read usage (free) and trigger a window (tiny quota)."""

from __future__ import annotations

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


PROVIDER_TITLES = {
    "claude": "Claude Code",
    "codex": "Codex",
    "commandcode": "Command Code",
    "glm": "GLM Coding Plan",
}
