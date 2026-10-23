"""MiniMax coding plan — usage endpoint + OpenAI-compatible ping.

Evidence: the usage envelope was read from a working third-party client
(``minimax-status``): ``model_remains[]`` items with ``start_time``, ``end_time``,
``remains_time``, ``current_interval_total_count`` and
``current_interval_usage_count``.

MiniMax bills in *aligned* blocks rather than a rolling window anchored on first
use, so the 5h window here is the item whose ``[start_time, end_time]`` spans about
five hours, and the reset is ``end_time`` — never "reset + 5h".

The ping goes to the OpenAI-compatible chat endpoint with ``max_tokens: 1``. The
path and model differ between the China and international deployments, so both are
configurable and the defaults only cover the international one.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..config import ProviderConfig
from ..http import HttpError, request_json
from .base import PingResult, Usage, Window, to_epoch

DEFAULT_BASE = "https://api.minimax.io/v1"
DEFAULT_PING_PATH = "/text/chatcompletion_v2"
DEFAULT_USAGE_URL = "https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains"
DEFAULT_MODEL = "MiniMax-M2"
DEFAULT_ENV_FILE = Path.home() / ".hermes" / ".env"

FIVE_HOURS = 5 * 3600.0
SIX_DAYS = 6 * 86400.0


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
    """Map ``model_remains[]`` onto 5h / weekly windows by block length."""
    usage = Usage(provider="minimax")
    data = payload.get("data") if isinstance(payload, dict) else None
    items = None
    if isinstance(data, dict):
        items = data.get("model_remains")
        usage.plan = data.get("plan") or data.get("plan_name")
    if items is None and isinstance(payload, dict):
        items = payload.get("model_remains")
    if not isinstance(items, list) or not items:
        raise RuntimeError("unexpected remains payload: no model_remains list")

    for entry in items:
        if not isinstance(entry, dict):
            continue
        start = to_epoch(entry.get("start_time"))
        end = to_epoch(entry.get("end_time"))
        total = entry.get("current_interval_total_count")
        used = entry.get("current_interval_usage_count")
        pct = None
        if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total > 0:
            pct = max(0.0, min(100.0, float(used) / float(total) * 100.0))
        reset_at = end
        if reset_at is None and isinstance(entry.get("remains_time"), (int, float)):
            remains = float(entry["remains_time"])
            reset_at = time.time() + (remains / 1000.0 if remains > 100_000 else remains)
        span = (end - start) if (start and end) else None
        window = Window(pct=pct, reset_at=reset_at, exceeded=(pct is not None and pct >= 100))
        if span is None or span <= 1.5 * FIVE_HOURS:
            # A payload without start/end still describes the primary window.
            if usage.five.pct is None and usage.five.reset_at is None:
                usage.five = window
        elif span >= SIX_DAYS:
            if usage.weekly.pct is None and usage.weekly.reset_at is None:
                usage.weekly = window
        if isinstance(used, (int, float)) and isinstance(total, (int, float)):
            label = entry.get("model_name") or entry.get("model") or "model"
            usage.details.append(f"{label}: {used:g} of {total:g} in this block")
            usage.details.append(
                f"block {time.strftime('%H:%M', time.localtime(start)) if start else '?'}–"
                f"{time.strftime('%H:%M', time.localtime(end)) if end else '?'}"
            )
    if (
        usage.five.pct is None
        and usage.five.reset_at is None
        and usage.weekly.pct is None
        and usage.weekly.reset_at is None
    ):
        raise RuntimeError("no 5h or weekly block in the MiniMax response")
    return usage


class MiniMaxProvider:
    name = "minimax"
    title = "MiniMax Coding Plan"

    def __init__(self, cfg: ProviderConfig, *, timeout: float = 20.0, ping_timeout: float = 180.0):
        self.cfg = cfg
        self.timeout = timeout
        self.ping_timeout = ping_timeout
        self.base = str(cfg.get("base_url") or DEFAULT_BASE).rstrip("/")
        self.ping_path = str(cfg.get("ping_path") or DEFAULT_PING_PATH)
        self.usage_url = str(cfg.get("usage_url") or DEFAULT_USAGE_URL)
        self.model = str(cfg.get("model") or DEFAULT_MODEL)
        self.prompt = str(cfg.get("prompt") or "ok")

    def api_key(self) -> str:
        inline = str(self.cfg.get("api_key") or "").strip()
        if inline:
            return inline
        env_name = str(self.cfg.get("api_key_env") or "MINIMAX_API_KEY")
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
        env_file = self.cfg.path("env_file", DEFAULT_ENV_FILE)
        for name in (env_name, "MINIMAX_API_KEY", "MINIMAX_CODING_KEY"):
            found = _read_env_file(env_file, (name,))
            if found:
                return found
        raise RuntimeError(
            f"no MiniMax key (set providers.minimax.api_key, ${env_name}, or {env_file})"
        )

    def usage(self) -> Usage:
        payload = request_json(
            self.usage_url,
            headers={"Authorization": f"Bearer {self.api_key()}"},
            timeout=self.timeout,
        )
        return parse_usage(payload)

    def ping(self) -> PingResult:
        url = self.base + ("" if self.ping_path.startswith("/") else "/") + self.ping_path
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


def build(cfg: ProviderConfig, *, general=None) -> MiniMaxProvider:
    return MiniMaxProvider(
        cfg,
        timeout=getattr(general, "read_timeout", 20.0),
        ping_timeout=getattr(general, "ping_timeout", 180.0),
    )
