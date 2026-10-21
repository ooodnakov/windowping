"""Single-file TOML configuration for windowping.

Everything lives in one file (default ``~/.config/windowping/config.toml``):
global scheduling knobs, all providers, and the Telegram bot.  Secrets may be
written inline (the file is created with mode 600 and should stay that way) or
pointed at an environment variable name.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("WINDOWPING_CONFIG") or Path.home() / ".config" / "windowping" / "config.toml"
)
DEFAULT_STATE_PATH = Path(
    os.environ.get("WINDOWPING_STATE") or Path.home() / ".local" / "state" / "windowping" / "state.json"
)

_DURATION_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$")
_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_duration(value, default: float) -> float:
    """``"90s"``/``"5m"``/``"2h"``/``"1d"``/``30`` (bare = seconds) -> seconds."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = _DURATION_RE.match(str(value))
    if not match:
        raise ValueError(f"cannot parse duration: {value!r}")
    return float(match.group(1)) * _UNITS[match.group(2) or "s"]


def _path(value, default: Path) -> Path:
    if value in (None, ""):
        return default
    return Path(str(value)).expanduser()


def _bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class General:
    weekly_threshold: float = 0.99
    reset_buffer: float = 300.0
    cooldown: float = 600.0
    register_grace: float = 1800.0
    tick_interval: float = 60.0
    ping_timeout: float = 180.0
    read_timeout: float = 20.0
    workdir: Path = field(default_factory=lambda: Path.home())
    state_file: Path = DEFAULT_STATE_PATH

    @property
    def weekly_percent(self) -> float:
        return self.weekly_threshold * 100.0


@dataclass
class ProviderConfig:
    """Raw provider section; concrete providers read the keys they care about."""

    name: str
    enabled: bool = True
    options: dict = field(default_factory=dict)

    def get(self, key, default=None):
        return self.options.get(key, default)

    def path(self, key, default: Path) -> Path:
        return _path(self.options.get(key), default)

    def num(self, key, default: float) -> float:
        return parse_duration(self.options.get(key), default)

    def flag(self, key, default: bool) -> bool:
        return _bool(self.options.get(key), default)


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    bot_token_env: str = "WINDOWPING_BOT_TOKEN"
    chat_id: int | None = None
    notify_events: tuple[str, ...] = ("ping", "error", "weekly")
    poll: bool = False
    allow_chat_ids: tuple[int, ...] = ()
    silent: bool = False

    def resolve_token(self) -> str:
        if self.bot_token.strip():
            return self.bot_token.strip()
        if self.bot_token_env and os.environ.get(self.bot_token_env):
            return os.environ[self.bot_token_env].strip()
        return ""

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.resolve_token()) and self.chat_id is not None


@dataclass
class Config:
    general: General
    providers: dict[str, ProviderConfig]
    telegram: TelegramConfig
    path: Path = DEFAULT_CONFIG_PATH

    def enabled_providers(self) -> list[ProviderConfig]:
        return [p for p in self.providers.values() if p.enabled]


DEFAULT_CONFIG_TEXT = """\
# windowping — keep 5h rate-limit windows back-to-back.
# One file for everything: scheduling, providers, Telegram.

[general]
# Stop pinging a provider once its weekly meter is at/above this fraction.
weekly_threshold = 0.99
# Wait this long after a window's reset before pinging (rollover safety).
reset_buffer = "5m"
# Never re-ping the same provider within this window.
cooldown = "10m"
# After a ping that has not shown up in the usage meter yet, wait this long.
register_grace = "30m"
# How often the watcher loop wakes up.
tick_interval = "60s"
# Wall clock budget for one provider ping.
ping_timeout = "180s"
# Directory the Codex ping runs in.
workdir = "~"

# Paths are optional; these are the defaults.
# state_file = "~/.local/state/windowping/state.json"

[providers.codex]
enabled = true
# "" = pick the cheapest model the Codex catalog offers at ping time.
model = ""
effort = "low"
prompt = "ok"
# How to trigger a window: "cli" runs `codex exec` (agent prompt included,
# ~12k tokens per ping) or "api" posts one raw Responses turn (~16 tokens) to
# the same ChatGPT backend endpoint. ping_fallback retries through the CLI if
# the API path fails, so a backend change cannot silently break window chaining.
ping_mode = "cli"
ping_fallback = true
# bin = "codex"
# auth_file = "~/.codex/auth.json"
# config_file = "~/.codex/config.toml"
# models_cache = "~/.codex/models_cache.json"

[providers.commandcode]
enabled = true
model = "deepseek/deepseek-v4.1-flash"
prompt = "ok"
base_url = "https://api.commandcode.ai"
# auth_file = "~/.commandcode/auth.json"

[providers.glm]
enabled = true
# Coding-plan tier model: legacy models (glm-4.5-flash) are served outside the
# plan and never start a 5h window.
model = "glm-5.3-flash"
prompt = "ok"
base_url = "https://api.z.ai/api/coding/paas/v4"
usage_url = "https://api.z.ai/api/monitor/usage/quota/limit"
# api_key = ""
api_key_env = "GLM_API_KEY"
env_file = "~/.hermes/.env"

[telegram]
enabled = false
# Prefer bot_token_env over pasting the token here.
bot_token = ""
bot_token_env = "WINDOWPING_BOT_TOKEN"
chat_id = 0
# Which transitions are worth a message: ping, error, weekly.
notify_events = ["ping", "error", "weekly"]
# Answer /status and /ping in the bot. Needs a token that no other process is
# long-polling (a Hermes gateway token will fight over getUpdates).
poll = false
silent = false
"""


def write_default_config(path: Path = DEFAULT_CONFIG_PATH, *, overwrite: bool = False) -> Path:
    path = Path(path).expanduser()
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    path.chmod(0o600)
    return path


def load(path: Path | None = None) -> Config:
    path = Path(path or DEFAULT_CONFIG_PATH).expanduser()
    if not path.exists():
        write_default_config(path)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    general_raw = raw.get("general") or {}
    general = General(
        weekly_threshold=float(general_raw.get("weekly_threshold", 0.99)),
        reset_buffer=parse_duration(general_raw.get("reset_buffer"), 300.0),
        cooldown=parse_duration(general_raw.get("cooldown"), 600.0),
        register_grace=parse_duration(general_raw.get("register_grace"), 1800.0),
        tick_interval=parse_duration(general_raw.get("tick_interval"), 60.0),
        ping_timeout=parse_duration(general_raw.get("ping_timeout"), 180.0),
        read_timeout=parse_duration(general_raw.get("read_timeout"), 20.0),
        workdir=_path(general_raw.get("workdir"), Path.home()),
        state_file=_path(general_raw.get("state_file"), DEFAULT_STATE_PATH),
    )
    if general.tick_interval < 5:
        raise ValueError("general.tick_interval must be at least 5s")

    providers: dict[str, ProviderConfig] = {}
    for name, section in (raw.get("providers") or {}).items():
        section = dict(section or {})
        enabled = _bool(section.pop("enabled", True), True)
        providers[name] = ProviderConfig(name=name, enabled=enabled, options=section)

    tg_raw = raw.get("telegram") or {}
    chat_id = tg_raw.get("chat_id")
    chat_id = int(chat_id) if chat_id not in (None, "", 0, "0") else None
    allow = tg_raw.get("allow_chat_ids")
    if allow is None:
        allow_ids = (chat_id,) if chat_id else ()
    else:
        allow_ids = tuple(int(x) for x in allow)
    telegram = TelegramConfig(
        enabled=_bool(tg_raw.get("enabled"), False),
        bot_token=str(tg_raw.get("bot_token") or ""),
        bot_token_env=str(tg_raw.get("bot_token_env") or "WINDOWPING_BOT_TOKEN"),
        chat_id=chat_id,
        notify_events=tuple(tg_raw.get("notify_events") or ("ping", "error", "weekly")),
        poll=_bool(tg_raw.get("poll"), False),
        allow_chat_ids=allow_ids,
        silent=_bool(tg_raw.get("silent"), False),
    )
    return Config(general=general, providers=providers, telegram=telegram, path=path)
