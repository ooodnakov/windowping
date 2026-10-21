"""Telegram command handler: /status, /ping, /help.

Replies are Telegram HTML and localized: the language follows the sender's
Telegram ``language_code`` when ``[telegram] lang = "auto"``, otherwise the
configured one. Every dynamic value is escaped in ``render``.
"""

from __future__ import annotations

import time

from .config import Config
from .i18n import t
from .providers import build_one, build_providers
from .render import esc, help_html, message_ping, message_ping_failed, telegram_status
from .watcher import Watcher

PROVIDER_ALIASES = {
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
        provider = build_one(self.config, name)
        if provider is None:
            known = ", ".join(self.config.providers) or "—"
            return [], t(lang, "unknown_provider", name=esc(name), known=esc(known))
        return [provider], None

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
        if command in ("/help", "/start", "/h", "/помощь"):
            return help_html(lang)
        return t(lang, "unknown_command", command=esc(command)) + "\n\n" + help_html(lang)
