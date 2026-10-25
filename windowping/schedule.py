"""Per-provider ping schedule: which days and hours a provider may be pinged.

The 5-hour window only exists to keep quota warm — there is no point in spending
a ping at the weekend on a plan nobody touches, and no point in opening a window
at 04:00 that will be reset before the first coffee.

One string per provider, in the style of the quiet-hours option::

    schedule = "mon-fri"                # weekdays only, any hour
    schedule = "mon-fri 07:00-23:30"    # weekdays, inside a window
    schedule = "weekends 10:00-02:00"   # wraps midnight
    schedule = "always"                 # the default when the key is absent
    schedule = "never"                   # keep the provider read-only

The schedule gates **pings only**. Usage is still read while a provider is off:
it is free, the dashboard needs it, and a weekly meter that fills up over the
weekend is still worth reporting.
"""

from __future__ import annotations

import datetime as dt
import re

_DAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}
_ALIASES = {
    "weekdays": frozenset({0, 1, 2, 3, 4}),
    "weekends": frozenset({5, 6}),
    "daily": frozenset({0, 1, 2, 3, 4, 5, 6}),
    "everyday": frozenset({0, 1, 2, 3, 4, 5, 6}),
    "always": None,
    "never": frozenset(),
}
_TIME_RANGE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")
_DAY_TOKEN = re.compile(r"^([a-z]{3})(?:\s*-\s*([a-z]{3}))?$")


def _parse_days(spec: str) -> frozenset[int] | None:
    """``mon-fri,sun`` -> {0,1,2,3,4,6}; ``always`` -> None."""
    text = spec.strip().lower().replace(" ", "")
    if text in _ALIASES:
        return _ALIASES[text]
    days: set[int] = set()
    for chunk in text.split(","):
        if not chunk:
            continue
        match = _DAY_TOKEN.match(chunk)
        if not match:
            raise ValueError(f"cannot parse days {chunk!r}, expected mon-fri or mon,wed,fri")
        first, last = match.group(1), match.group(2)
        if first not in _DAYS:
            raise ValueError(f"unknown weekday {first!r}")
        if last is None:
            days.add(_DAYS[first])
            continue
        if last not in _DAYS:
            raise ValueError(f"unknown weekday {last!r}")
        start, end = _DAYS[first], _DAYS[last]
        if start <= end:
            days.update(range(start, end + 1))
        else:  # fri-mon wraps the week
            days.update(range(start, 7))
            days.update(range(0, end + 1))
    if not days:
        raise ValueError("empty day list")
    return frozenset(days)


def _parse_time(value: str) -> tuple[int, int]:
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError(f"time out of range: {value!r}")
    return hour, minute


class Schedule:
    """An immutable schedule; ``None`` in place of one means "always allowed"."""

    __slots__ = ("days", "start", "end", "text")

    def __init__(
        self,
        days: frozenset[int] | None,
        start: tuple[int, int] | None,
        end: tuple[int, int] | None,
        text: str,
    ):
        self.days = days
        self.start = start
        self.end = end
        self.text = text

    # -- parsing ------------------------------------------------------------

    @classmethod
    def parse(cls, spec: str | None) -> "Schedule | None":
        """Return a schedule, or None when the provider may always be pinged."""
        raw = (spec or "").strip()
        if not raw or raw.lower() in ("always", "*", "any"):
            return None
        lowered = raw.lower()
        for alias in ("always", "never"):
            if lowered == alias:
                return cls(_ALIASES[alias], None, None, alias)

        parts = raw.split()
        if len(parts) > 2:
            raise ValueError(f"cannot parse schedule {raw!r}, expected '<days> [HH:MM-HH:MM]'")
        days: frozenset[int] | None = None
        window: tuple[tuple[int, int], tuple[int, int]] | None = None

        for part in parts:
            time_match = _TIME_RANGE.match(part)
            if time_match:
                start = _parse_time(f"{time_match.group(1)}:{time_match.group(2)}")
                end = _parse_time(f"{time_match.group(3)}:{time_match.group(4)}")
                window = (start, end)
            else:
                if days is not None:
                    raise ValueError(f"two day lists in schedule {raw!r}")
                days = _parse_days(part)
        if days is None and window is None:
            raise ValueError(f"cannot parse schedule {raw!r}")
        if window and window[0] == window[1]:
            # A zero-length window would mean "never", which is `never`, not a typo
            # that silently disables pinging.
            raise ValueError(f"schedule {raw!r} has an empty time window")
        return cls(days, window[0] if window else None, window[1] if window else None, raw)

    # -- queries ------------------------------------------------------------

    def allows(self, moment: dt.datetime | None = None) -> bool:
        moment = moment or dt.datetime.now()
        weekday = moment.weekday()
        if self.days is not None and not self.days:
            return False  # "never"
        if self.start is None or self.end is None:
            return self.days is None or weekday in self.days
        minute = moment.hour * 60 + moment.minute
        start = self.start[0] * 60 + self.start[1]
        end = self.end[0] * 60 + self.end[1]
        same_day = self.days is None or weekday in self.days
        if start < end:
            return same_day and start <= minute < end
        # Wraps midnight: the evening part belongs to today, the morning part to
        # the day that opened the window — and only until `end`.
        if minute >= start:
            return same_day
        if minute >= end:
            return False
        previous = (weekday - 1) % 7
        return self.days is None or previous in self.days

    def next_open(self, moment: dt.datetime | None = None) -> dt.datetime | None:
        """First moment at or after ``moment`` that is allowed; None for "never"."""
        moment = (moment or dt.datetime.now()).replace(second=0, microsecond=0)
        if self.days is not None and not self.days:
            return None
        if self.allows(moment):
            return moment
        candidate = moment
        for _ in range(8 * 24 * 60):  # a week plus a day of slack
            candidate += dt.timedelta(minutes=1)
            if self.allows(candidate):
                return candidate
        return None

    def describe(self) -> str:
        if self.days is not None and not self.days:
            return "never"
        if self.days is None or self.days == frozenset({0, 1, 2, 3, 4, 5, 6}):
            days = "every day"
        elif self.days == frozenset({0, 1, 2, 3, 4}):
            days = "mon-fri"
        elif self.days == frozenset({5, 6}):
            days = "weekends"
        else:
            order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            days = ",".join(order[day] for day in sorted(self.days))
        if self.start and self.end:
            return f"{days} {self.start[0]:02d}:{self.start[1]:02d}-{self.end[0]:02d}:{self.end[1]:02d}"
        return days

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Schedule({self.describe()!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Schedule) and self.describe() == other.describe()


def parse(spec: str | None) -> Schedule | None:
    return Schedule.parse(spec)
