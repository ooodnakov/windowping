"""Terminal and Telegram rendering.

Two renderers over the same data: plain text for the CLI (``status_text``) and
Telegram HTML for the bot (``telegram_status`` / ``message_*``).  Every piece of
dynamic text is escaped — provider errors and API messages end up in Telegram's
HTML parser.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import time

from .i18n import help_text, t
from .providers.base import Usage

TELEGRAM_TITLE = "windowping"
WINDOW_LABELS = {"five": "5h", "weekly": "weekly"}


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #


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


def fmt_hm(ts: float | None) -> str:
    if ts is None:
        return "—"
    return dt.datetime.fromtimestamp(ts).astimezone().strftime("%H:%M")


def fmt_tokens(tokens: int | None) -> str:
    if tokens is None:
        return "—"
    if tokens < 1000:
        return f"{tokens} tok"
    return f"{tokens / 1000:.1f}k tok"


def bar(pct: float | None, width: int = 10) -> str:
    if pct is None:
        return "[?]"
    filled = max(0, min(width, round(pct / 100 * width)))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def bar_bare(pct: float | None, width: int = 10) -> str:
    if pct is None:
        return "?" * width
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


# --------------------------------------------------------------------------- #
# plain text (CLI)
# --------------------------------------------------------------------------- #


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
    """Render a status block for the terminal."""
    blocks: list[str] = []
    for name, usage, error in rows:
        if error:
            blocks.append(f"{name}\n  error: {error}")
        elif usage is not None:
            blocks.append("\n".join(usage_lines(usage, now)))
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# telegram html
# --------------------------------------------------------------------------- #

_PRE_LABEL = 6  # width of "weekly"
_PRE_BAR = 10
_PRE_PCT = 4  # width of " 69%"
_PRE_RESET = 7  # width of "3h32m"


def _state_icon(usage: Usage | None, error: str | None, threshold: float = 99.0) -> str:
    if error:
        return "🔴"
    if usage is None:
        return "⚪️"
    if usage.weekly.pct is not None and usage.weekly.pct >= threshold:
        return "🟠"
    return "🟢"


def _pre_line(label: str, window, now: float, lang: str = "en") -> str:
    pad = f"{label:<{_PRE_LABEL}}"
    if not window.enforced:
        return f"{pad} {'':<{_PRE_BAR}}  {t(lang, 'no_limit')}"
    pct = "  ?" if window.pct is None else f"{round(window.pct):>3}%"
    if window.reset_at is None:
        reset = "       —"
    else:
        reset = fmt_delta(window.reset_at - now).rjust(_PRE_RESET)
    return f"{pad} {bar_bare(window.pct, _PRE_BAR)} {pct}  {reset}"


_DETAIL_RULES: dict[str, list[tuple[re.Pattern[str], str]]] = {
    "ru": [
        (re.compile(r"^(?P<count>\d+) reset credit\(s\) available$"), "{count} сброс(а) в запасе"),
        (re.compile(r"^\$(?P<amount>[\d.]+) monthly credits left$"), "на месяц осталось ${amount}"),
        (re.compile(r"^no usage windows on this plan$"), "на плане нет окон"),
        (re.compile(r"^(?P<label>.+) weekly (?P<pct>\d+)%$"), "{label} — неделя {pct}%"),
    ],
}


def _human_detail(text: str, lang: str = "en") -> str:
    """Provider details are English; Russian users get the known lines translated."""
    for pattern, template in _DETAIL_RULES.get(lang, []):
        match = pattern.match(text)
        if match:
            return template.format(**match.groupdict())
    return text


def _compact_details(usage: Usage, lang: str = "en", limit: int = 2) -> list[str]:
    """Keep only short, non-duplicating extras (balances, credits)."""
    picked: list[str] = []
    for line in usage.details:
        text = line.strip()
        if not text or text.startswith(("5h ", "weekly ", "5h credits", "weekly credits")):
            continue
        picked.append(esc(_human_detail(text, lang)))
        if len(picked) >= limit:
            break
    return picked


def telegram_status(
    rows: list[tuple[str, Usage | None, str | None]],
    now: float | None = None,
    *,
    header: str | None = None,
    threshold: float = 99.0,
    lang: str = "en",
) -> str:
    """Compact monospace dashboard for one or more providers."""
    now = now if now is not None else time.time()
    blocks: list[str] = []
    for name, usage, error in rows:
        icon = _state_icon(usage, error, threshold)
        title = f"<b>{esc(name)}</b>"
        if usage is not None and usage.plan:
            title += f" · <i>{esc(usage.plan)}</i>"
        if error:
            label = t(lang, "error_label")
            blocks.append(f"{icon} {title}\n<pre>{label}: {esc(error)[:300]}</pre>")
            continue
        if usage is None:
            continue
        pre = "\n".join(
            [
                _pre_line("5h", usage.five, now, lang),
                _pre_line("weekly", usage.weekly, now, lang),
            ]
        )
        block = f"{icon} {title}\n<pre>{pre}</pre>"
        details = _compact_details(usage, lang)
        if details:
            block += "\n" + " · ".join(details)
        blocks.append(block)
    body = "\n\n".join(blocks)
    if header:
        return f"<b>{esc(header)}</b>\n\n{body}"
    return body


def message_ping(
    title: str,
    model: str | None,
    tokens: int | None,
    seconds: float | None,
    reason: str | None = None,
    reset_at: float | None = None,
    lang: str = "en",
) -> str:
    stats = []
    if model:
        stats.append(f"<code>{esc(model)}</code>")
    if tokens:
        stats.append(fmt_tokens(tokens))
    if seconds:
        stats.append(f"{seconds:.1f}s")
    text = f"✅ <b>{esc(title)}</b> — {t(lang, 'ping_ok')}"
    if stats:
        text += "\n" + " · ".join(stats)
    if reset_at:
        text += "\n<i>" + esc(t(lang, "window_until", time=fmt_hm(reset_at))) + "</i>"
    elif reason:
        text += f"\n<i>{esc(reason)}</i>"
    return text


def message_ping_failed(title: str, error: str | None, lang: str = "en") -> str:
    return (
        f"⚠️ <b>{esc(title)}</b> — {t(lang, 'ping_failed')}\n"
        f"<pre>{esc(error)[:400]}</pre>"
    )


def message_weekly(
    title: str,
    pct: float | None,
    reset_ts: float | None,
    now: float | None = None,
    lang: str = "en",
) -> str:
    now = now if now is not None else time.time()
    left = t(lang, "weekly_resets", delta=fmt_delta(reset_ts - now)) if reset_ts else ""
    pct_text = f"{pct:.0f}%" if pct is not None else "100%"
    return (
        f"⛔️ <b>{esc(title)}</b> — {t(lang, 'weekly_reached')}\n"
        f"{pct_text}{esc(left)}\n"
        f"{t(lang, 'weekly_wait')}"
    )


def message_error(title: str, error: str | None, lang: str = "en") -> str:
    return (
        f"⚠️ <b>{esc(title)}</b> — {t(lang, 'usage_error')}\n"
        f"<pre>{esc(error)[:400]}</pre>"
    )


def message_escalate(title: str, count: int, error: str | None, lang: str = "en") -> str:
    text = (
        f"🆘 <b>{esc(title)}</b> — {esc(t(lang, 'escalate_title'))}\n"
        f"<i>{esc(t(lang, 'escalate_body', count=count))}</i>"
    )
    if error:
        text += f"\n<pre>{esc(error)[:300]}</pre>"
    return text + f"\n{esc(t(lang, 'escalate_hint'))}"


def message_recovered(title: str, lang: str = "en") -> str:
    return f"♻️ <b>{esc(title)}</b> — {t(lang, 'recovered')}"


def message_test(config_path: str, providers: list[str], lang: str = "en") -> str:
    return (
        f"👋 <b>{TELEGRAM_TITLE}</b> {t(lang, 'test_ok')}\n"
        f"<pre>config    {esc(config_path)}\n"
        f"providers {esc(', '.join(providers) or '—')}</pre>"
    )


def _hours(value: float) -> str:
    if value >= 10:
        return f"{value:.0f}"
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _stats_body(stats, lang: str) -> list[str]:
    """Aligned ``<pre>`` lines shared by /stats and the morning digest."""
    rows = [
        (t(lang, "stats_windows"), str(stats.pings)),
        (t(lang, "stats_coverage"), f"{_hours(stats.coverage_hours)}h"),
    ]
    if stats.failures:
        rows.append((t(lang, "stats_failed"), str(stats.failures)))
    if stats.tokens:
        rows.append((t(lang, "stats_tokens"), f"{stats.tokens:,}"))
    if stats.seconds:
        rows.append((t(lang, "stats_time"), f"{stats.seconds:.0f}s"))
    width = max(len(label) for label, _ in rows)
    return [f"{label.ljust(width)}  {value}" for label, value in rows]


def telegram_stats(stats, lang: str = "en", *, digest: bool = False) -> str:
    head = "🌙" if digest else "📊"
    label = t(lang, "digest_hint") if digest else t(lang, "stats_header")
    period = t(lang, "stats_period", days=stats.days)
    text = f"{head} <b>{esc(label)}</b> · <i>{esc(period)}</i>"
    if not stats.pings and not stats.failures:
        return text + f"\n<i>{esc(t(lang, 'stats_empty'))}</i>"
    text += "\n<pre>" + "\n".join(esc(line) for line in _stats_body(stats, lang)) + "</pre>"
    per_provider = [(name, s) for name, s in stats.providers.items() if name and (s.pings or s.failures)]
    if per_provider and not digest:
        per_provider.sort(key=lambda item: (-item[1].pings, item[0]))
        lines = []
        for name, bucket in per_provider:
            bits = [f"{bucket.pings}"]
            if bucket.tokens:
                bits.append(f"{bucket.tokens} tok")
            if bucket.failures:
                bits.append(f"✗{bucket.failures}")
            lines.append(f"{name.ljust(12)} {' · '.join(bits)}")
        text += f"\n<b>{esc(t(lang, 'stats_by_provider'))}</b>\n<pre>" + "\n".join(esc(l) for l in lines) + "</pre>"
    return text


def stats_text(stats, *, provider: str | None = None) -> str:
    """Plain-text summary for the CLI (English, like the rest of the CLI)."""
    period = f"last {stats.days}d"
    if not stats.pings and not stats.failures:
        return f"windowping stats — {period}\n\nno pings recorded yet"
    lines = [f"windowping stats — {period}", ""]
    lines.append(f"windows opened   {stats.pings}   (~{_hours(stats.coverage_hours)}h of coverage)")
    if stats.failures:
        lines.append(f"failed pings     {stats.failures}")
    if stats.errors:
        lines.append(f"usage errors     {stats.errors}")
    if stats.weekly_stops:
        lines.append(f"weekly stops     {stats.weekly_stops}")
    if stats.tokens:
        lines.append(f"tokens spent     {stats.tokens:,}")
    if stats.seconds:
        lines.append(f"time in pings    {stats.seconds:.1f}s")
    rows = [
        (name, bucket)
        for name, bucket in stats.providers.items()
        if name and (provider is None or name == provider) and (bucket.pings or bucket.failures)
    ]
    if rows:
        rows.sort(key=lambda item: (-item[1].pings, item[0]))
        lines.append("")
        lines.append("by provider")
        width = max(len(name) for name, _ in rows)
        for name, bucket in rows:
            bits = [f"{bucket.pings} window(s)"]
            if bucket.tokens:
                bits.append(f"{bucket.tokens:,} tok")
            if bucket.seconds:
                bits.append(f"{bucket.seconds:.1f}s")
            if bucket.failures:
                bits.append(f"{bucket.failures} failed")
            lines.append(f"  {name.ljust(width)}  {' · '.join(bits)}")
    return "\n".join(lines)


HELP_HTML = help_text("en")


def help_html(lang: str | None = "en") -> str:
    return help_text(lang, TELEGRAM_TITLE)


def strip_tags(text: str) -> str:
    """Fallback when Telegram rejects an entity: send readable plain text."""
    text = re.sub(r"<pre>|<b>|<i>|<code>", "", text)
    text = re.sub(r"</(pre|b|i|code)>", "", text)
    return html.unescape(text)
