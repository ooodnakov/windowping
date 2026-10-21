"""Telegram command handler: /status, /ping, /help.

Replies are Telegram HTML; every dynamic value is escaped in ``render``.
"""

from __future__ import annotations

import time

from .config import Config
from .providers import build_one, build_providers
from .render import HELP_HTML, esc, message_ping, message_ping_failed, telegram_status
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
    def __init__(self, config: Config):
        self.config = config

    # -- helpers ---------------------------------------------------------- #

    def _resolve(self, argument: str):
        name = PROVIDER_ALIASES.get(argument.strip().lower(), argument.strip().lower())
        if not name:
            return build_providers(self.config), None
        provider = build_one(self.config, name)
        if provider is None:
            known = ", ".join(self.config.providers) or "—"
            return [], f"неизвестный провайдер: <code>{esc(name)}</code>\nесть: {esc(known)}"
        return [provider], None

    def status(self, argument: str = "") -> str:
        providers, error = self._resolve(argument)
        if error:
            return error
        if not providers:
            return "нет включённых провайдеров"
        rows = []
        for provider in providers:
            try:
                rows.append((provider.name, provider.usage(), None))
            except Exception as exc:  # noqa: BLE001 - report, never raise
                rows.append((provider.name, None, str(exc)))
        header = "лимиты" if len(rows) > 1 else None
        return telegram_status(rows, threshold=self.config.general.weekly_percent, header=header)

    def ping(self, argument: str = "") -> str:
        providers, error = self._resolve(argument)
        if error:
            return error
        if not providers:
            return "нет включённых провайдеров"
        watcher = Watcher(self.config)
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
                    )
                )
            else:
                blocks.append(message_ping_failed(provider.title, result.error))
        watcher.state.save()
        return "\n\n".join(blocks)

    # -- dispatch --------------------------------------------------------- #

    def handle(self, text: str) -> str | None:
        text = text.strip()
        if not text:
            return None
        if text.startswith("/"):
            command, _, argument = text.partition(" ")
            command = command.split("@", 1)[0].lower()
        else:
            # Bare words work too, so "status" in a hurry is not a syntax error.
            command, _, argument = text.partition(" ")
            command = "/" + command.lower()
        argument = argument.strip()

        if command in ("/status", "/s", "/лимиты"):
            return self.status(argument)
        if command in ("/ping", "/p", "/пинг"):
            return self.ping(argument)
        if command in ("/help", "/start", "/h", "/помощь"):
            return HELP_HTML
        return f"не знаю команду <code>{esc(command)}</code>\n\n{HELP_HTML}"
