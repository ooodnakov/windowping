"""Provider registry."""

from __future__ import annotations

from ..config import Config, ProviderConfig
from . import claude, codex, commandcode, glm, kimi, minimax
from .base import PROVIDER_TITLES, PingResult, Provider, Usage, Window

BUILDERS = {
    "claude": claude.build,
    "codex": codex.build,
    "commandcode": commandcode.build,
    "glm": glm.build,
    "kimi": kimi.build,
    "minimax": minimax.build,
}

# Order used for display when the config does not dictate one.
DEFAULT_ORDER = ("codex", "commandcode", "glm", "claude", "kimi", "minimax")


def build_providers(config: Config) -> list[Provider]:
    """Instantiate every enabled provider from the config, in display order."""
    order = [n for n in DEFAULT_ORDER if n in config.providers]
    order += [n for n in config.providers if n not in order]
    providers: list[Provider] = []
    for name in order:
        section = config.providers[name]
        if not section.enabled:
            continue
        builder = BUILDERS.get(name)
        if builder is None:
            continue
        providers.append(builder(section, general=config.general))
    return providers


def build_one(config: Config, name: str) -> Provider | None:
    section: ProviderConfig | None = config.providers.get(name)
    if section is None or name not in BUILDERS:
        return None
    return BUILDERS[name](section, general=config.general)


def title(name: str) -> str:
    return PROVIDER_TITLES.get(name, name)


__all__ = [
    "BUILDERS",
    "DEFAULT_ORDER",
    "PingResult",
    "Provider",
    "Usage",
    "Window",
    "build_one",
    "build_providers",
    "claude",
    "codex",
    "commandcode",
    "glm",
    "kimi",
    "minimax",
    "title",
]
