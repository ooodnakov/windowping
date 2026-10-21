"""Telegram command handler: /status, /ping, /help."""

from __future__ import annotations

import time

from .config import Config
from .providers import build_providers, build_one
from .render import fmt_delta, status_text, usage_lines
from .watcher import Watcher

HELP_TEXT = """windowping

/status — окна и лимиты всех провайдеров
/status glm — только GLM
/ping — пнуть все включённые провайдеры
/ping codex — пнуть только Codex
/help — это сообщение"""


class BotCommands:
    def __init__(self, config: Config):
        self.config = config

    # -- helpers ---------------------------------------------------------- #

    def _providers(self, argument: str):
        name = argument.strip().lower()
        if not name:
            return build_providers(self.config), None
        provider = build_one(self.config, name)
        if provider is None:
            return [], f"неизвестный провайдер: {name}"
        return [provider], None

    def status(self, argument: str = "") -> str:
        providers, error = self._providers(argument)
        if error:
            return error
        rows = []
        for provider in providers:
            try:
                rows.append((provider.name, provider.usage(), None))
            except Exception as exc:  # noqa: BLE001 - report, never raise
                rows.append((provider.name, None, str(exc)))
        return status_text(rows) if rows else "нет включённых провайдеров"

    def ping(self, argument: str = "") -> str:
        providers, error = self._providers(argument)
        if error:
            return error
        if not providers:
            return "нет включённых провайдеров"
        watcher = Watcher(self.config)
        lines = []
        last_usage = None
        for provider in providers:
            try:
                last_usage = provider.usage()
            except Exception:  # noqa: BLE001 - ping anyway, state stays unknown
                last_usage = None
            result = provider.ping()
            if result.ok:
                bits = []
                if result.seconds:
                    bits.append(f"{result.seconds:.1f}s")
                if result.tokens:
                    bits.append(f"{result.tokens} tokens")
                suffix = f" ({', '.join(bits)})" if bits else ""
                lines.append(f"✓ {provider.title}{suffix}\n{result.model or 'модель по умолчанию'}")
                watcher.state.update(
                    provider.name,
                    last_ping=time.time(),
                    pinged_for_reset=(last_usage.five.reset_at if last_usage else None),
                )
            else:
                lines.append(f"✗ {provider.title}: {result.error}")
        watcher.state.save()
        if last_usage is not None and len(providers) == 1:
            lines.append("")
            lines.extend(usage_lines(last_usage))
        return "\n".join(lines)

    # -- dispatch --------------------------------------------------------- #

    def handle(self, text: str) -> str | None:
        text = text.strip()
        if not text.startswith("/"):
            return None
        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        if command in ("/status", "/s"):
            return self.status(argument)
        if command in ("/ping", "/p"):
            return self.ping(argument)
        if command in ("/help", "/start", "/h"):
            return HELP_TEXT
        return f"не знаю такую команду: {command}\n\n{HELP_TEXT}"
