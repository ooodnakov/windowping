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


def _pre_line(label: str, window, now: float) -> str:
    pad = f"{label:<{_PRE_LABEL}}"
    if not window.enforced:
        return f"{pad} {'':<{_PRE_BAR}}  нет лимита"
    pct = "  ?" if window.pct is None else f"{round(window.pct):>3}%"
    if window.reset_at is None:
        reset = "       —"
    else:
        reset = fmt_delta(window.reset_at - now).rjust(_PRE_RESET)
    return f"{pad} {bar_bare(window.pct, _PRE_BAR)} {pct}  {reset}"


_DETAIL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(\d+) reset credit\(s\) available$"), r"\1 сброс(а) в запасе"),
    (re.compile(r"^\$([\d.]+) monthly credits left$"), r"на месяц осталось $\1"),
    (re.compile(r"^no usage windows on this plan$"), "на плане нет окон"),
]


def _human_detail(text: str) -> str:
    for pattern, template in _DETAIL_RULES:
        match = pattern.match(text)
        if match:
            return match.expand(template)
    return text


def _compact_details(usage: Usage, limit: int = 2) -> list[str]:
    """Keep only short, non-duplicating extras (balances, credits)."""
    picked: list[str] = []
    for line in usage.details:
        text = line.strip()
        if not text or text.startswith(("5h ", "weekly ", "5h credits", "weekly credits")):
            continue
        picked.append(esc(_human_detail(text)))
        if len(picked) >= limit:
            break
    return picked


def telegram_status(
    rows: list[tuple[str, Usage | None, str | None]],
    now: float | None = None,
    *,
    header: str | None = None,
    threshold: float = 99.0,
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
            blocks.append(f"{icon} {title}\n<pre>error: {esc(error)[:300]}</pre>")
            continue
        if usage is None:
            continue
        pre = "\n".join(
            [_pre_line("5h", usage.five, now), _pre_line("weekly", usage.weekly, now)]
        )
        block = f"{icon} {title}\n<pre>{pre}</pre>"
        details = _compact_details(usage)
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
) -> str:
    stats = []
    if model:
        stats.append(f"<code>{esc(model)}</code>")
    if tokens:
        stats.append(fmt_tokens(tokens))
    if seconds:
        stats.append(f"{seconds:.1f}s")
    text = f"✅ <b>{esc(title)}</b> — новое окно"
    if stats:
        text += "\n" + " · ".join(stats)
    if reset_at:
        text += f"\n<i>5h-окно до {fmt_hm(reset_at)}</i>"
    elif reason:
        text += f"\n<i>{esc(reason)}</i>"
    return text


def message_ping_failed(title: str, error: str | None) -> str:
    return f"⚠️ <b>{esc(title)}</b> — пинг не прошёл\n<pre>{esc(error)[:400]}</pre>"


def message_weekly(
    title: str, pct: float | None, reset_ts: float | None, now: float | None = None
) -> str:
    now = now if now is not None else time.time()
    left = f" · сброс через {fmt_delta(reset_ts - now)}" if reset_ts else ""
    pct_text = f"{pct:.0f}%" if pct is not None else "100%"
    return (
        f"⛔️ <b>{esc(title)}</b> — недельный лимит выбран\n"
        f"{pct_text}{left}\n"
        "Пинги ждут сброса."
    )


def message_error(title: str, error: str | None) -> str:
    return f"⚠️ <b>{esc(title)}</b> — ошибка чтения лимитов\n<pre>{esc(error)[:400]}</pre>"


def message_recovered(title: str) -> str:
    return f"♻️ <b>{esc(title)}</b> — снова на связи"


def message_test(config_path: str, providers: list[str]) -> str:
    return (
        f"👋 <b>{TELEGRAM_TITLE}</b> на связи\n"
        f"<pre>config    {esc(config_path)}\n"
        f"providers {esc(', '.join(providers) or '—')}</pre>"
    )


HELP_HTML = f"""<b>{TELEGRAM_TITLE}</b>
<i>держит 5-часовые окна лимитов склеенными</i>

<b>Команды</b>
/status — все провайдеры
/status glm — только GLM
/ping — пнуть всё сейчас
/ping codex — пнуть один
/help — это сообщение

<b>Как это работает</b>
После сброса окна отправляется один минимальный запрос, чтобы новое окно
началось сразу. Когда недельный лимит выбран, пинги ждут сброса.

<b>Обозначения</b>
<pre>5h      ███████░░░  69%  3h32m
weekly  ███░░░░░░░  30%  6d7h

🟢 всё ок    🟠 неделя выбрана
🔴 ошибка    ⚪️ нет данных</pre>
Последняя колонка — сколько осталось до сброса."""


def strip_tags(text: str) -> str:
    """Fallback when Telegram rejects an entity: send readable plain text."""
    text = re.sub(r"<pre>|<b>|<i>|<code>", "", text)
    text = re.sub(r"</(pre|b|i|code)>", "", text)
    return html.unescape(text)
