"""Provider registry, including several accounts of the same provider.

One plan per provider is the common case, so a provider is built straight from
its config section. Heavy users have two ChatGPT logins or two GLM keys, though,
and ``[providers.codex.accounts.work]`` makes each of them a separate instance:

    [providers.codex]
    enabled = true
    ping_mode = "api"

    [providers.codex.accounts.work]
    auth_file = "~/.codex-work/auth.json"

    [providers.codex.accounts.personal]
    auth_file = "~/.codex/auth.json"

Each instance is named ``codex:work`` / ``codex:personal``, keeps its own state,
history and windows, and shows up as its own row in ``status``. Account keys
override the provider's keys; ``enabled = false`` on an account skips just that
one.
"""

from __future__ import annotations

from ..config import Config, ProviderConfig, _bool
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
SEPARATOR = ":"


def split_instance(name: str) -> tuple[str, str | None]:
    """``"codex:work"`` -> ``("codex", "work")``."""
    base, _, label = name.partition(SEPARATOR)
    return base, (label or None)


def instances(name: str, section: ProviderConfig) -> list[tuple[str, ProviderConfig]]:
    """Expand one config section into its instances (one per account)."""
    accounts = section.get("accounts")
    if not isinstance(accounts, dict) or not accounts:
        return [(name, section)]
    base_options = {key: value for key, value in section.options.items() if key != "accounts"}
    out: list[tuple[str, ProviderConfig]] = []
    for label, overrides in accounts.items():
        overrides = dict(overrides or {})
        options = {**base_options, **overrides}
        options.pop("accounts", None)
        enabled = section.enabled and _bool(overrides.get("enabled"), True)
        out.append(
            (
                f"{name}{SEPARATOR}{label}",
                ProviderConfig(name=name, enabled=enabled, options=options),
            )
        )
    return out


def _instantiate(builder, instance: str, cfg: ProviderConfig, general) -> Provider:
    provider = builder(cfg, general=general)
    base, label = split_instance(instance)
    if label is not None:
        provider.name = instance
        title_text = str(cfg.get("title") or PROVIDER_TITLES.get(base, base))
        provider.title = f"{title_text} ({label})"
    return provider


def build_providers(config: Config) -> list[Provider]:
    """Instantiate every enabled provider (and every enabled account)."""
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
        for instance, instance_cfg in instances(name, section):
            if not instance_cfg.enabled:
                continue
            providers.append(_instantiate(builder, instance, instance_cfg, config.general))
    return providers


def build_matching(config: Config, name: str) -> list[Provider]:
    """Every instance matching ``name`` — exact (``codex:work``) or by base (``codex``)."""
    base, label = split_instance(name)
    section = config.providers.get(base)
    if section is None or base not in BUILDERS or not section.enabled:
        return []
    builder = BUILDERS[base]
    wanted = f"{base}{SEPARATOR}{label}" if label else None
    built: list[Provider] = []
    for instance, instance_cfg in instances(base, section):
        if not instance_cfg.enabled:
            continue
        if wanted is not None and instance != wanted:
            continue
        built.append(_instantiate(builder, instance, instance_cfg, config.general))
    return built


def build_one(config: Config, name: str) -> Provider | None:
    """The first instance matching ``name`` (with accounts, ``codex`` = first one)."""
    matches = build_matching(config, name)
    return matches[0] if matches else None


def title(name: str) -> str:
    return PROVIDER_TITLES.get(split_instance(name)[0], name)


__all__ = [
    "BUILDERS",
    "DEFAULT_ORDER",
    "PingResult",
    "Provider",
    "Usage",
    "Window",
    "build_matching",
    "build_one",
    "build_providers",
    "claude",
    "codex",
    "commandcode",
    "glm",
    "instances",
    "kimi",
    "minimax",
    "split_instance",
    "title",
]
