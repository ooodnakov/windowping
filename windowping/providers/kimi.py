"""Kimi for Coding (Moonshot) — usage endpoint + OpenAI-compatible ping.

Evidence: the usage envelope was read from a working third-party client
(``kimi-code-usage``), which reports ``data.usages[]`` items carrying a
``window`` of ``{duration, timeUnit}`` plus ``used``/``limit``/``resetTime``.
Window length is part of the payload, so nothing here assumes "5h" — the item
whose window is 5 hours *is* the 5h window, whichever position it sits in.

The ping goes to the OpenAI-compatible ``/coding/v1`` surface with
``max_tokens: 1``. Model names on that surface change with the plan, so
``[providers.kimi] model`` is required for a real deployment; the default is
only a sane starting point.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..config import ProviderConfig
from ..http import HttpError, request_json
from .base import PingResult, Usage, Window, to_epoch

DEFAULT_BASE = "https://api.kimi.com/coding/v1"
DEFAULT_USAGE_URL = "https://api.kimi.com/coding/v1/usages"
DEFAULT_MODEL = "kimi-k2-turbo-preview"
DEFAULT_ENV_FILE = Path.home() / ".hermes" / ".env"

_UNIT_MINUTES = {
    "minute": 1.0,
    "minutes": 1.0,
    "hour": 60.0,
    "hours": 60.0,
    "day": 1440.0,
    "days": 1440.0,
    "week": 10080.0,
    "weeks": 10080.0,
    "month": 43200.0,
    "months": 43200.0,
}


def _read_env_file(path: Path, names: tuple[str, ...]) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in names:
            value = value.strip().strip("\"'")
            if value:
                return value
    return None


def window_minutes(entry: dict) -> float | None:
    """Length of the window an item describes, in minutes."""
    window = entry.get("window")
    source = window if isinstance(window, dict) else entry
    duration = source.get("duration")
    if duration is None:
        duration = source.get("windowDuration") or source.get("size")
    unit = str(source.get("timeUnit") or source.get("unit") or "hour").strip().lower()
    factor = _UNIT_MINUTES.get(unit)
    if isinstance(duration, str) and duration.strip().isdigit():
        duration = int(duration.strip())
    if isinstance(duration, (int, float)) and factor:
        return float(duration) * factor
    return None


def _pct(entry: dict) -> float | None:
    used = entry.get("used")
    limit = entry.get("limit") or entry.get("total")
    if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
        return max(0.0, min(100.0, float(used) / float(limit) * 100.0))
    for key in ("percentage", "usedPercent", "used_percent"):
        value = entry.get(key)
        if isinstance(value, (int, float)):
            return max(0.0, min(100.0, float(value)))
    return None


def parse_usage(payload: dict) -> Usage:
    usage = Usage(provider="kimi")
    data = payload.get("data") if isinstance(payload, dict) else None
    items = None
    if isinstance(data, dict):
        items = data.get("usages") or data.get("items")
        usage.plan = data.get("plan") or data.get("level")
    if items is None and isinstance(payload, dict):
        items = payload.get("usages")
    if not isinstance(items, list):
        raise RuntimeError("unexpected usages payload: no data.usages list")

    for entry in items:
        if not isinstance(entry, dict):
            continue
        minutes = window_minutes(entry)
        pct = _pct(entry)
        reset = to_epoch(entry.get("resetTime") or entry.get("resets_at") or entry.get("reset_at"))
        window = Window(pct=pct, reset_at=reset, exceeded=(pct is not None and pct >= 100))
        if minutes == 300:
            usage.five = window
        elif minutes is not None and 7 * 1440 <= minutes < 30 * 1440:
            usage.weekly = window
        elif minutes is not None:
            usage.details.append(f"{minutes / 60:g}h window: {pct:.0f}%" if pct is not None else f"{minutes / 60:g}h window")
        used, limit = entry.get("used"), entry.get("limit") or entry.get("total")
        if isinstance(used, (int, float)) and isinstance(limit, (int, float)):
            usage.details.append(f"{entry.get('name') or 'credits'}: {used:g} of {limit:g}")
    if usage.five.reset_at is None and usage.five.pct is None and usage.weekly.reset_at is None:
        raise RuntimeError("no 5h or weekly window in the Kimi response")
    return usage


class KimiProvider:
    name = "kimi"
    title = "Kimi for Coding"

    def __init__(self, cfg: ProviderConfig, *, timeout: float = 20.0, ping_timeout: float = 180.0):
        self.cfg = cfg
        self.timeout = timeout
        self.ping_timeout = ping_timeout
        self.base = str(cfg.get("base_url") or DEFAULT_BASE).rstrip("/")
        self.usage_url = str(cfg.get("usage_url") or DEFAULT_USAGE_URL)
        self.model = str(cfg.get("model") or DEFAULT_MODEL)
        self.prompt = str(cfg.get("prompt") or "ok")

    def api_key(self) -> str:
        inline = str(self.cfg.get("api_key") or "").strip()
        if inline:
            return inline
        env_name = str(self.cfg.get("api_key_env") or "KIMI_API_KEY")
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
        env_file = self.cfg.path("env_file", DEFAULT_ENV_FILE)
        for name in (env_name, "KIMI_API_KEY", "MOONSHOT_API_KEY"):
            found = _read_env_file(env_file, (name,))
            if found:
                return found
        raise RuntimeError(
            f"no Kimi api key (set providers.kimi.api_key, ${env_name}, or {env_file})"
        )

    def usage(self) -> Usage:
        payload = request_json(
            self.usage_url,
            headers={"Authorization": f"Bearer {self.api_key()}"},
            timeout=self.timeout,
        )
        return parse_usage(payload)

    def ping(self) -> PingResult:
        url = f"{self.base}/chat/completions"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.prompt}],
            "max_tokens": 1,
        }
        started = time.monotonic()
        try:
            payload = request_json(
                url,
                method="POST",
                headers={"Authorization": f"Bearer {self.api_key()}"},
                body=body,
                timeout=self.ping_timeout,
            )
        except HttpError as exc:
            return PingResult(ok=False, error=str(exc), model=self.model)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            return PingResult(ok=False, error=str(exc), model=self.model)
        tokens = (payload.get("usage") or {}).get("total_tokens")
        return PingResult(
            ok=True,
            seconds=time.monotonic() - started,
            model=payload.get("model") or self.model,
            tokens=tokens if isinstance(tokens, int) else None,
        )


def build(cfg: ProviderConfig, *, general=None) -> KimiProvider:
    return KimiProvider(
        cfg,
        timeout=getattr(general, "read_timeout", 20.0),
        ping_timeout=getattr(general, "ping_timeout", 180.0),
    )
