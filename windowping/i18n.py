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
        "help": """<b>{name}</b>
<i>keeps 5-hour rate-limit windows back-to-back</i>

<b>Commands</b>
/status — all providers
/status glm — one provider
/ping — trigger a window now
/ping codex — one provider
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
        "help": """<b>{name}</b>
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
Последняя колонка — сколько осталось до сброса.""",
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
