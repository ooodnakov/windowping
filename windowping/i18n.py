"""Message catalogue for the Telegram surface (English + Russian).

The rest of the project — CLI output, docs, comments, identifiers — is English
only. This table exists because the bot talks to humans, and one deployment may
serve both languages: replies follow the sender's Telegram ``language_code``
when ``[telegram] lang = "auto"``, notifications follow the owner's last seen
language.
"""

from __future__ import annotations

DEFAULT = "en"
SUPPORTED = ("en", "ru")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "limits_header": "limits",
        "no_limit": "no limit",
        "error_label": "error",
        "ping_ok": "new window",
        "window_until": "5h window until {time}",
        "ping_failed": "ping failed",
        "weekly_reached": "weekly limit reached",
        "weekly_resets": " · resets in {delta}",
        "weekly_wait": "Pings are waiting for the reset.",
        "usage_error": "cannot read usage",
        "recovered": "is back",
        "test_ok": "is running",
        "unknown_provider": "unknown provider: <code>{name}</code>\navailable: {known}",
        "no_providers": "no providers enabled",
        "unknown_command": "unknown command <code>{command}</code>",
        "reply_error": "error: {error}",
        "detail_reset_credits": "{count} reset credit(s) available",
        "detail_monthly": "${amount} monthly credits left",
        "detail_no_windows": "no usage windows on this plan",
        "escalate_title": "needs a hand",
        "escalate_body": "{count} pings in a row failed",
        "escalate_hint": "check it with: windowping doctor",
        "digest_hint": "night report",
        "stats_header": "stats",
        "stats_period": "last {days}d",
        "stats_windows": "windows",
        "stats_coverage": "covered",
        "stats_failed": "failed",
        "stats_tokens": "tokens",
        "stats_time": "in pings",
        "stats_empty": "no pings recorded yet",
        "stats_by_provider": "by provider",
        "help": """<b>{name}</b>
<i>keeps 5-hour rate-limit windows back-to-back</i>

<b>Commands</b>
/status — all providers
/status glm — one provider
/ping — trigger a window now
/ping codex — one provider
/stats — what it did over 7 days
/stats 30 — over 30 days
/schedule — when each provider may be pinged
/help — this message

<b>How it works</b>
After a window resets, one minimal request is sent so the next window starts
right away. When the weekly cap is reached, pings wait for the reset.

<b>Legend</b>
<pre>5h      ███████░░░  69%  3h32m
weekly  ███░░░░░░░  30%  6d7h

🟢 fine      🟠 week used up
🔴 error     ⚪️ no data</pre>
The last column is the time left until the reset.""",
        "card_title": "📊 usage",
        "card_footer": "updated {updated} · next auto at {next}",
        "card_footer_muted": "🔇 muted until {until}",
        "btn_refresh": "🔄 Refresh",
        "btn_ping": "⏱ Ping",
        "btn_stats": "📈 Stats",
        "btn_schedule": "🗓 Schedule",
        "btn_new": "🆕 New card",
        "btn_mute": "🔇 Mute 8h",
        "toast_refreshed": "refreshed",
        "toast_muted": "quiet for 8h",
        "toast_pinged": "ping sent",
        "pings_title": "{count} windows opened",
        "until_reset": "until {when}",
        "schedule_header": "<b>Ping schedule</b>",
        "schedule_always": "always",
        "schedule_allowed": "allowed now",
        "schedule_next": "next {when}",
        "schedule_never": "never",
        "schedule_hint": "Set <code>schedule</code> per provider in config.toml: "
                         "\"mon-fri\", \"mon-fri 07:00-23:30\", \"weekends\", \"never\".",
    },
    "ru": {
        "limits_header": "лимиты",
        "no_limit": "нет лимита",
        "error_label": "ошибка",
        "ping_ok": "новое окно",
        "window_until": "5h-окно до {time}",
        "ping_failed": "пинг не прошёл",
        "weekly_reached": "недельный лимит выбран",
        "weekly_resets": " · сброс через {delta}",
        "weekly_wait": "Пинги ждут сброса.",
        "usage_error": "ошибка чтения лимитов",
        "recovered": "снова на связи",
        "test_ok": "на связи",
        "unknown_provider": "неизвестный провайдер: <code>{name}</code>\nесть: {known}",
        "no_providers": "нет включённых провайдеров",
        "unknown_command": "не знаю команду <code>{command}</code>",
        "reply_error": "ошибка: {error}",
        "detail_reset_credits": "{count} сброс(а) в запасе",
        "detail_monthly": "на месяц осталось ${amount}",
        "detail_no_windows": "на плане нет окон",
        "escalate_title": "нужна помощь",
        "escalate_body": "{count} пингов подряд не прошли",
        "escalate_hint": "проверь: windowping doctor",
        "digest_hint": "отчёт за ночь",
        "stats_header": "статистика",
        "stats_period": "за {days}д",
        "stats_windows": "окон",
        "stats_coverage": "покрыто",
        "stats_failed": "сбоев",
        "stats_tokens": "токенов",
        "stats_time": "в пингах",
        "stats_empty": "пингов пока не было",
        "stats_by_provider": "по провайдерам",
        "help": """<b>{name}</b>
<i>держит 5-часовые окна лимитов склеенными</i>

<b>Команды</b>
/status — все провайдеры
/status glm — только GLM
/ping — пнуть всё сейчас
/ping codex — пнуть один
/stats — что сделано за 7 дней
/stats 30 — за 30 дней
/schedule — когда можно пинговать каждого
/help — это сообщение

<b>Как это работает</b>
После сброса окна отправляется один минимальный запрос, чтобы новое окно
началось сразу. Когда недельный лимит выбран, пинги ждут сброса.

<b>Обозначения</b>
<pre>5h      ███████░░░  69%  3h32m
weekly  ███░░░░░░░  30%  6d7h

🟢 всё ок    🟠 неделя выбрана
🔴 ошибка    ⚪️ нет данных</pre>
Последняя колонка — сколько осталось до сброса.""",
        "card_title": "📊 лимиты",
        "card_footer": "обновлено {updated} · авто в {next}",
        "card_footer_muted": "🔇 до {until}",
        "btn_refresh": "🔄 Обновить",
        "btn_ping": "⏱ Пнуть",
        "btn_stats": "📈 Статистика",
        "btn_schedule": "🗓 Расписание",
        "btn_new": "🆕 Новая",
        "btn_mute": "🔇 Мьют 8ч",
        "toast_refreshed": "обновлено",
        "toast_muted": "молчу 8ч",
        "toast_pinged": "пинг отправлен",
        "pings_title": "открыто окон: {count}",
        "until_reset": "до {when}",
        "schedule_header": "<b>Расписание пингов</b>",
        "schedule_always": "всегда",
        "schedule_allowed": "можно сейчас",
        "schedule_next": "следующий {when}",
        "schedule_never": "никогда",
        "schedule_hint": "Задаётся по провайдеру в config.toml: "
                         "\"mon-fri\", \"mon-fri 07:00-23:30\", \"weekends\", \"never\".",
    },
}


def normalize(lang: str | None) -> str:
    """Map ``ru-RU``/``RU``/``en-GB`` onto a catalogue key."""
    if not lang:
        return DEFAULT
    base = lang.replace("_", "-").split("-", 1)[0].strip().lower()
    return base if base in SUPPORTED else DEFAULT


def t(lang: str | None, key: str, **values: object) -> str:
    """Look up a message, falling back to English for missing keys."""
    table = STRINGS[normalize(lang)]
    template = table.get(key) or STRINGS[DEFAULT].get(key) or key
    return template.format(**values) if values else template


def help_text(lang: str | None, name: str = "windowping") -> str:
    return t(lang, "help", name=name)
