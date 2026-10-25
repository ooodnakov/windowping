"""Persisting the last usage reading.

Reading usage costs a request per provider per tick, which at a one-minute tick
and three providers is 4 320 requests a day for numbers that usually do not
move. The watcher therefore keeps the last reading in its state file and asks
again on a schedule (``usage_interval``, default 30 minutes), when a window is
due to reset, or when the owner presses Refresh.

The snapshot is plain JSON, so the state file stays readable and the dashboard
can use it too.
"""

from __future__ import annotations

from .providers.base import Usage, Window


def _window(window: Window) -> dict:
    return {
        "pct": window.pct,
        "reset_at": window.reset_at,
        "enforced": window.enforced,
        "exceeded": window.exceeded,
    }


def from_usage(usage: Usage, taken_at: float) -> dict:
    return {
        "taken_at": taken_at,
        "plan": usage.plan,
        "five": _window(usage.five),
        "weekly": _window(usage.weekly),
        "details": list(usage.details or []),
    }


def _restore_window(raw) -> Window:
    if not isinstance(raw, dict):
        return Window()
    return Window(
        pct=raw.get("pct"),
        reset_at=raw.get("reset_at"),
        enforced=bool(raw.get("enforced", True)),
        exceeded=raw.get("exceeded"),
    )


def to_usage(name: str, raw) -> Usage | None:
    """Rebuild a ``Usage`` from its snapshot; None when the snapshot is unusable."""
    if not isinstance(raw, dict) or not raw.get("taken_at"):
        return None
    return Usage(
        provider=name,
        five=_restore_window(raw.get("five")),
        weekly=_restore_window(raw.get("weekly")),
        plan=raw.get("plan"),
        details=list(raw.get("details") or []),
    )


def taken_at(raw) -> float:
    try:
        return float((raw or {}).get("taken_at") or 0)
    except (TypeError, ValueError):
        return 0.0
