"""GLM Coding Plan (Z.ai) — quota monitor endpoint + OpenAI-compatible ping."""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..config import ProviderConfig, parse_duration
from ..http import HttpError, request_json
from .base import PingResult, Usage, Window

DEFAULT_BASE = "https://api.z.ai/api/coding/paas/v4"
DEFAULT_USAGE_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
DEFAULT_ENV_FILE = Path.home() / ".hermes" / ".env"

_TOKEN_TYPES = ("TOKENS_LIMIT", "CREDIT_LIMIT")
_UNIT_FIVE_HOURS = 3
_UNIT_WEEKLY = 6


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


def parse_usage(payload: dict) -> Usage:
    """Map the quota/limit envelope onto 5h / weekly windows.

    Window identity comes from ``unit`` (3 = 5 hours, 6 = week/month bucket),
    never from list position — Z.ai is free to reorder the limits array.
    """
    usage = Usage(provider="glm")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("unexpected quota payload: no data object")
    usage.plan = data.get("level")
    for entry in data.get("limits") or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type") or "").upper()
        pct = entry.get("percentage")
        if pct is None:
            used, cap = entry.get("currentValue"), entry.get("usage")
            if isinstance(used, (int, float)) and isinstance(cap, (int, float)) and cap > 0:
                pct = used / cap * 100.0
        reset = entry.get("nextResetTime")
        if isinstance(reset, (int, float)) and reset > 0:
            reset = reset / 1000.0 if reset > 100_000_000_000 else float(reset)
        else:
            reset = None
        pct_value = max(0.0, min(100.0, float(pct))) if pct is not None else None

        if kind in _TOKEN_TYPES and entry.get("unit") == _UNIT_FIVE_HOURS:
            usage.five = Window(
                pct=pct_value,
                reset_at=reset,
                exceeded=(pct_value is not None and pct_value >= 100),
            )
            used = entry.get("currentValue")
            cap = entry.get("usage")
            if isinstance(used, (int, float)):
                usage.details.append(f"5h credits used: {used:g} of {cap:g}" if isinstance(cap, (int, float)) else f"5h credits used: {used:g}")
        elif kind in _TOKEN_TYPES and entry.get("unit") == _UNIT_WEEKLY:
            usage.weekly = Window(
                pct=pct_value,
                reset_at=reset,
                exceeded=(pct_value is not None and pct_value >= 100),
            )
            used = entry.get("currentValue")
            cap = entry.get("usage")
            if isinstance(used, (int, float)) and isinstance(cap, (int, float)):
                usage.details.append(f"weekly credits used: {used:g} of {cap:g}")
    return usage


class GLMProvider:
    name = "glm"
    title = "GLM Coding Plan"

    def __init__(self, cfg: ProviderConfig, *, timeout: float = 20.0, ping_timeout: float = 180.0):
        self.cfg = cfg
        self.timeout = timeout
        self.ping_timeout = ping_timeout
        self.base = str(cfg.get("base_url") or DEFAULT_BASE)
        self.usage_url = str(cfg.get("usage_url") or DEFAULT_USAGE_URL)
        self.model = str(cfg.get("model") or "glm-5.3-flash")
        self.prompt = str(cfg.get("prompt") or "ok")
        self.details_width = 8

    # -- credentials ------------------------------------------------------- #

    def api_key(self) -> str:
        inline = str(self.cfg.get("api_key") or "").strip()
        if inline:
            return inline
        env_name = str(self.cfg.get("api_key_env") or "GLM_API_KEY")
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
        env_file = self.cfg.path("env_file", DEFAULT_ENV_FILE)
        for name in (env_name, "ZAI_API_KEY", "GLM_API_KEY", "Z_AI_API_KEY"):
            found = _read_env_file(env_file, (name,))
            if found:
                return found
        raise RuntimeError(
            f"no GLM api key (set providers.glm.api_key, ${env_name}, or {env_file})"
        )

    # -- provider interface ------------------------------------------------ #

    def usage(self) -> Usage:
        payload = request_json(
            self.usage_url,
            headers={"Authorization": f"Bearer {self.api_key()}"},
            timeout=self.timeout,
        )
        if payload.get("success") is False:
            raise RuntimeError("no active GLM coding plan on this key")
        return parse_usage(payload)

    def ping(self) -> PingResult:
        url = self.base.rstrip("/") + "/chat/completions"
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


def build(cfg: ProviderConfig, *, general=None) -> GLMProvider:
    return GLMProvider(
        cfg,
        timeout=getattr(general, "read_timeout", 20.0),
        ping_timeout=getattr(general, "ping_timeout", 180.0),
    )
