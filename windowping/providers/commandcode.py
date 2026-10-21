"""Command Code (commandcode.ai) — alpha billing routes the official CLI uses.

``/alpha/billing/credits`` reports ``windowLimits.fiveHour`` and
``windowLimits.weekly`` as ``{used, cap, resetAt}`` in USD credits; the ping is
a one-token chat completion against the provider's OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..config import ProviderConfig
from ..http import HttpError, request_json
from .base import PingResult, Usage, Window

DEFAULT_BASE = "https://api.commandcode.ai"
DEFAULT_AUTH_FILE = Path.home() / ".commandcode" / "auth.json"
CLI_USER_AGENT = "command-code/1.53.0"


def parse_windows(payload: dict) -> Usage:
    usage = Usage(provider="commandcode")
    limits = payload.get("windowLimits") or {}
    if limits.get("limited") is False:
        usage.details.append("no usage windows on this plan")

    def window(block) -> Window:
        if not isinstance(block, dict):
            return Window(enforced=False)
        used, cap = block.get("used"), block.get("cap")
        pct = None
        if isinstance(used, (int, float)) and isinstance(cap, (int, float)) and cap > 0:
            pct = max(0.0, min(100.0, used / cap * 100.0))
        reset = block.get("resetAt")
        reset_at = reset / 1000.0 if isinstance(reset, (int, float)) and reset else None
        return Window(pct=pct, reset_at=reset_at, exceeded=block.get("exceeded"))

    usage.five = window(limits.get("fiveHour"))
    usage.weekly = window(limits.get("weekly"))

    credits = payload.get("credits") or {}
    monthly = credits.get("monthlyCredits")
    if isinstance(monthly, (int, float)):
        usage.details.append(f"${monthly:.2f} monthly credits left")
    for label, key in (("5h", "five"), ("weekly", "weekly")):
        block = limits.get("fiveHour" if key == "five" else "weekly") or {}
        used, cap = block.get("used"), block.get("cap")
        if isinstance(used, (int, float)) and isinstance(cap, (int, float)):
            usage.details.append(f"{label} ${used:.2f} of ${cap:.2f}")
    return usage


class CommandCodeProvider:
    name = "commandcode"
    title = "Command Code"

    def __init__(self, cfg: ProviderConfig, *, timeout: float = 20.0, ping_timeout: float = 180.0):
        self.cfg = cfg
        self.timeout = timeout
        self.ping_timeout = ping_timeout
        self.base = str(cfg.get("base_url") or DEFAULT_BASE).rstrip("/")
        self.model = str(cfg.get("model") or "deepseek/deepseek-v4.1-flash")
        self.prompt = str(cfg.get("prompt") or "ok")
        self.auth_file = cfg.path("auth_file", DEFAULT_AUTH_FILE)

    def api_key(self) -> str:
        try:
            data = json.loads(Path(self.auth_file).read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"cannot read {self.auth_file}: {exc}") from None
        except ValueError:
            raise RuntimeError(f"{self.auth_file} is not valid JSON") from None
        key = data.get("apiKey") if isinstance(data, dict) else None
        if not isinstance(key, str) or not key.strip():
            raise RuntimeError(f"no apiKey in {self.auth_file}")
        return key.strip()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key()}", "User-Agent": CLI_USER_AGENT}

    def usage(self) -> Usage:
        payload = request_json(
            f"{self.base}/alpha/billing/credits", headers=self._headers(), timeout=self.timeout
        )
        return parse_windows(payload)

    def ping(self) -> PingResult:
        url = f"{self.base}/provider/v1/chat/completions"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.prompt}],
            "max_tokens": 1,
        }
        started = time.monotonic()
        try:
            payload = request_json(
                url, method="POST", headers=self._headers(), body=body, timeout=self.ping_timeout
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


def build(cfg: ProviderConfig, *, general=None) -> CommandCodeProvider:
    return CommandCodeProvider(
        cfg,
        timeout=getattr(general, "read_timeout", 20.0),
        ping_timeout=getattr(general, "ping_timeout", 180.0),
    )
