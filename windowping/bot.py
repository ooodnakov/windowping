"""Telegram command handler: /status, /ping, /help.

Replies are Telegram HTML and localized: the language follows the sender's
Telegram ``language_code`` when ``[telegram] lang = "auto"``, otherwise the
configured one. Every dynamic value is escaped in ``render``.
"""

from __future__ import annotations

import datetime as dt
import time

from .config import Config
from .i18n import t
from .notify.telegram import send_message
from .providers import build_matching, build_providers
from .render import esc, help_html, message_ping, message_ping_failed, telegram_stats, telegram_status
from .watcher import Watcher

PROVIDER_ALIASES = {
    "anthropic": "claude",
    "claude": "claude",
    "claude-code": "claude",
    "cc": "commandcode",
    "command": "commandcode",
    "command-code": "commandcode",
    "codex": "codex",
    "glm": "glm",
    "zai": "glm",
    "z.ai": "glm",
}


class BotCommands:
    def __init__(self, config: Config, watcher: Watcher | None = None):
        self.config = config
        # Sharing the watcher keeps a single State instance behind the process.
        self.watcher = watcher or Watcher(config)

    # -- helpers ---------------------------------------------------------- #

    def _remember_lang(self, lang: str) -> None:
        """Notifications go to the owner, so the owner's last language wins."""
        chat_id = self.config.telegram.chat_id
        if chat_id is None or self.config.telegram.lang != "auto":
            return
        if self.watcher.state.chat_lang(chat_id) == lang:
            return
        self.watcher.state.set_chat_lang(chat_id, lang)
        self.watcher.state.save()

    def _resolve(self, argument: str, lang: str):
        name = PROVIDER_ALIASES.get(argument.strip().lower(), argument.strip().lower())
        if not name:
            return build_providers(self.config), None
        # "codex" means every account of codex; "codex:work" means just that one.
        providers = build_matching(self.config, name)
        if not providers:
            known = ", ".join(self.config.providers) or "—"
            return [], t(lang, "unknown_provider", name=esc(name), known=esc(known))
        return providers, None

    def status(self, argument: str = "", lang: str = "en") -> str:
        providers, error = self._resolve(argument, lang)
        if error:
            return error
        if not providers:
            return t(lang, "no_providers")
        rows = []
        for provider in providers:
            try:
                rows.append((provider.name, provider.usage(), None))
            except Exception as exc:  # noqa: BLE001 - report, never raise
                rows.append((provider.name, None, str(exc)))
        header = t(lang, "limits_header") if len(rows) > 1 else None
        return telegram_status(
            rows, threshold=self.config.general.weekly_percent, header=header, lang=lang
        )

    def ping(self, argument: str = "", lang: str = "en") -> str:
        providers, error = self._resolve(argument, lang)
        if error:
            return error
        if not providers:
            return t(lang, "no_providers")
        watcher = self.watcher
        blocks: list[str] = []
        for provider in providers:
            try:
                before = provider.usage()
            except Exception:  # noqa: BLE001 - ping anyway, state stays unknown
                before = None
            result = provider.ping()
            if result.ok:
                watcher.state.update(
                    provider.name,
                    last_ping=time.time(),
                    pinged_for_reset=(before.five.reset_at if before else None),
                    last_ping_result={
                        "ok": True,
                        "model": result.model,
                        "tokens": result.tokens,
                        "seconds": round(result.seconds, 1),
                    },
                )
                after = None
                try:
                    after = provider.usage()
                except Exception:  # noqa: BLE001 - cosmetic only
                    after = None
                blocks.append(
                    message_ping(
                        provider.title,
                        result.model,
                        result.tokens,
                        result.seconds,
                        reset_at=(after.five.reset_at if after else None),
                        lang=lang,
                    )
                )
            else:
                blocks.append(message_ping_failed(provider.title, result.error, lang))
        watcher.state.save()
        return "\n\n".join(blocks)

    def schedule(self, argument: str = "", lang: str = "en") -> str:
        """Show each provider's ping schedule and the next moment it opens."""
        now = dt.datetime.now()
        wanted = argument.strip().lower()
        aliases = PROVIDER_ALIASES
        providers = build_providers(self.config)
        if wanted:
            base = aliases.get(wanted, wanted)
            providers = [p for p in providers if p.name == base or p.name.split(":")[0] == base]
        if not providers:
            return t(lang, "schedule_header") + "\n—"

        lines = []
        for provider in providers:
            schedule = self.watcher.provider_schedule(provider)
            title = esc(provider.title)
            if schedule is None:
                state = t(lang, "schedule_always")
                lines.append(f"<b>{title}</b>: {state}")
                continue
            if schedule.allows(now):
                state = t(lang, "schedule_allowed")
            else:
                upcoming = schedule.next_open(now)
                state = (
                    t(lang, "schedule_never")
                    if upcoming is None
                    else t(lang, "schedule_next", when=upcoming.strftime("%a %H:%M"))
                )
            lines.append(f"<b>{title}</b>: {esc(schedule.describe())} — {state}")
        return t(lang, "schedule_header") + "\n" + "\n".join(lines) + "\n\n" + t(lang, "schedule_hint")

    def stats(self, argument: str = "", lang: str = "en") -> str:
        days = 7
        argument = argument.strip()
        if argument:
            try:
                days = max(1, min(365, int(argument)))
            except ValueError:
                days = 7
        return telegram_stats(self.watcher.history.stats(days=days), lang)

    # -- dispatch --------------------------------------------------------- #

    def handle(self, text: str, sender_lang: str | None = None) -> str | None:
        text = text.strip()
        if not text:
            return None
        lang = self.config.telegram.resolve_lang(sender_lang)
        self._remember_lang(lang)

        if text.startswith("/"):
            command, _, argument = text.partition(" ")
            command = command.split("@", 1)[0].lower()
        else:
            # Bare words work too, so "status" in a hurry is not a syntax error.
            command, _, argument = text.partition(" ")
            command = "/" + command.lower()
        argument = argument.strip()

        if command in ("/status", "/s", "/лимиты"):
            return self.status(argument, lang)
        if command in ("/ping", "/p", "/пинг"):
            return self.ping(argument, lang)
        if command in ("/stats", "/stat", "/стата", "/статистика"):
            return self.stats(argument, lang)
        if command in ("/schedule", "/sched", "/расписание"):
            return self.schedule(argument, lang)
        if command in ("/help", "/start", "/h", "/помощь"):
            return help_html(lang)
        return t(lang, "unknown_command", command=esc(command)) + "\n\n" + help_html(lang)

    # -- buttons ---------------------------------------------------------- #

    def _send(self, chat_id: int, text: str) -> None:
        token = self.config.telegram.resolve_token()
        if not token:
            return
        send_message(token, chat_id, text, silent=self.config.telegram.in_quiet_hours())

    def handle_callback(self, data: str, chat_id: int, message_id: int, sender_lang: str | None = None) -> None:
        """A button under the card: act, then repaint the same message."""
        lang = self.config.telegram.resolve_lang(sender_lang)
        providers = build_providers(self.config)
        data = (data or "").strip()
        # One line per button press: enough to tell a manual refresh from the
        # scheduled one when reading the journal later.
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} button: {data}", flush=True)

        if data == "refresh":
            self.watcher.refresh_usage(providers)
            return
        if data == "status":
            self.watcher.repaint_card(providers)
            return
        if data == "ping":
            # Same rules as the watcher: schedule, weekly cap, one ping per window.
            self.watcher.tick(providers)
            return
        if data == "mute":
            self.watcher.mute()
            self.watcher.repaint_card(providers)
            return
        if data == "stats":
            self._send(chat_id, self.stats("", lang))
            return
        if data == "schedule":
            self._send(chat_id, self.schedule("", lang))
