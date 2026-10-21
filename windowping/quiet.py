"""Quiet hours: deliver Telegram messages without a notification sound.

Telegram has no server-side schedule, but every send accepts
``disable_notification``, so the bot can keep talking while staying silent. A
range that wraps midnight (``"12:00-08:00"``) is the normal case: quiet starts at
noon and ends at 8 the next morning.
"""

from __future__ import annotations

import datetime as dt
import re

_RANGE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")
Ranges = list[tuple[dt.time, dt.time]]


def parse_ranges(spec: str | None) -> Ranges:
    """``"12:00-08:00, 23:30-07:00"`` -> ``[(12:00, 08:00), (23:30, 07:00)]``.

    Raises ``ValueError`` on anything malformed: a typo in a quiet-hours spec
    should be loud at startup, not silently leave the phone buzzing at 3am.
    """
    if not spec or not spec.strip():
        return []
    ranges: Ranges = []
    for chunk in spec.split(","):
        if not chunk.strip():
            continue
        match = _RANGE.match(chunk)
        if not match:
            raise ValueError(f"cannot parse quiet hours {chunk.strip()!r}, expected HH:MM-HH:MM")
        start_h, start_m, end_h, end_m = (int(part) for part in match.groups())
        if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
            raise ValueError(f"quiet hours out of range: {chunk.strip()!r}")
        ranges.append((dt.time(start_h, start_m), dt.time(end_h, end_m)))
    return ranges


def in_quiet_hours(spec: str | None, now: dt.datetime | None = None) -> bool:
    """True when ``now`` falls inside any range of ``spec`` (local time by default)."""
    ranges = parse_ranges(spec)
    if not ranges:
        return False
    moment = (now or dt.datetime.now()).time().replace(second=0, microsecond=0)
    for start, end in ranges:
        if start == end:
            continue  # a zero-length window means "never", not "always"
        if start < end:
            if start <= moment < end:
                return True
        elif moment >= start or moment < end:  # wraps midnight
            return True
    return False


def describe(spec: str | None) -> str:
    """Short human-readable summary, for logs and ``config show``."""
    ranges = parse_ranges(spec)
    if not ranges:
        return "off"
    return ", ".join(f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}" for start, end in ranges)
