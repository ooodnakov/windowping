"""Terminal / Telegram rendering helpers (shared by CLI and bot)."""

from __future__ import annotations

import datetime as dt
import time

from .providers.base import Usage

WINDOW_LABELS = {"five": "5h", "weekly": "weekly"}


def fmt_delta(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 0:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    days, rest = divmod(seconds, 86400)
    return f"{days}d{rest // 3600}h"


def fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return dt.datetime.fromtimestamp(ts).astimezone().strftime("%a %H:%M %Z")


def bar(pct: float | None, width: int = 10) -> str:
    if pct is None:
        return "[?]"
    filled = max(0, min(width, round(pct / 100 * width)))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def window_line(label: str, window, now: float | None = None) -> str:
    now = now if now is not None else time.time()
    label = f"{label:<6}"
    if not window.enforced:
        return f"  {label} not currently enforced"
    if window.pct is None:
        return f"  {label} unknown"
    if window.reset_at is None:
        reset = "not started"
    else:
        reset = fmt_delta(window.reset_at - now) + f"  ({fmt_ts(window.reset_at)})"
    return f"  {label} {bar(window.pct)} {window.pct:5.1f}% used   resets {reset}"


def usage_lines(usage: Usage, now: float | None = None, *, details: bool = True) -> list[str]:
    head = usage.provider if not usage.plan else f"{usage.provider} ({usage.plan})"
    lines = [head]
    lines.append(window_line("5h", usage.five, now))
    lines.append(window_line("weekly", usage.weekly, now))
    if details:
        lines.extend(f"  {line}" for line in usage.details)
    return lines


def status_text(rows: list[tuple[str, Usage | None, str | None]], now: float | None = None) -> str:
    """Render a status block.  ``rows`` are (provider name, usage, error)."""
    blocks: list[str] = []
    for name, usage, error in rows:
        if error:
            blocks.append(f"{name}\n  error: {error}")
        elif usage is not None:
            blocks.append("\n".join(usage_lines(usage, now)))
    return "\n\n".join(blocks)
