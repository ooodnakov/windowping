"""Codex (ChatGPT plan) — OAuth usage endpoint + ``codex exec`` ping.

Auth is read from ``~/.codex/auth.json`` (the Codex CLI's own file), refreshed
through the same OAuth client the CLI uses, and written back so both tools stay
in sync.  Usage is a read-only hit on the ChatGPT backend; the ping is a
headless ``codex exec --ephemeral`` turn, which is the only way to actually
start a subscription-backed window.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Iterator

from ..config import ProviderConfig
from ..http import HttpError, request_json
from .base import PingResult, Usage, Window

DEFAULT_BASE = "https://chatgpt.com/backend-api"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
RESPONSES_PATH = "/codex/responses"
# The backend rejects anything smaller ("Expected a value >= 16").
API_MIN_OUTPUT_TOKENS = 16
CLI_ORIGINATOR = "codex_cli_rs"
DEFAULT_AUTH_FILE = Path.home() / ".codex" / "auth.json"
DEFAULT_CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_MODELS_CACHE = Path.home() / ".codex" / "models_cache.json"

WEEKLY_MIN_SECONDS = 2 * 24 * 3600
BUDGET_MARKERS = ("affordable", "cheap", "low cost", "low-cost", "mini", "luna")


def classify_windows(rate_limit: dict, now: float) -> tuple[Window, Window]:
    """Split primary/secondary by window length, not by position.

    OpenAI has moved the 5h window in and out of existence; position no longer
    identifies a window, so anything shorter than two days is the 5h one.
    """
    five = Window(enforced=False)
    weekly = Window(enforced=False)
    for key in ("primary_window", "secondary_window"):
        block = (rate_limit or {}).get(key)
        if not isinstance(block, dict):
            continue
        length = block.get("limit_window_seconds")
        pct = block.get("used_percent")
        reset_at = block.get("reset_at")
        if reset_at is None and block.get("reset_after_seconds") is not None:
            reset_at = now + float(block["reset_after_seconds"])
        window = Window(
            pct=float(pct) if isinstance(pct, (int, float)) else None,
            reset_at=float(reset_at) if isinstance(reset_at, (int, float)) and reset_at else None,
            enforced=True,
        )
        if isinstance(length, (int, float)) and length >= WEEKLY_MIN_SECONDS:
            weekly = window
        else:
            five = window
    return five, weekly


def parse_usage(payload: dict, now: float | None = None) -> Usage:
    now = now if now is not None else time.time()
    usage = Usage(provider="codex")
    rate_limit = payload.get("rate_limit") or {}
    usage.five, usage.weekly = classify_windows(rate_limit, now)
    usage.plan = payload.get("plan_type")
    credits_block = payload.get("rate_limit_reset_credits") or {}
    count = credits_block.get("available_count")
    if isinstance(count, int) and count > 0:
        usage.details.append(f"{count} reset credit(s) available")
    return usage


def cheapest_model(cache_path: Path) -> str:
    """Cheapest catalogued model by description wording; "" when unclear.

    The catalog carries no price field, so the budget tier is the only signal
    it exposes.  Ties break toward the entry ranked furthest from the flagship.
    """
    try:
        data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    models = data.get("models") if isinstance(data, dict) else data
    if not isinstance(models, list):
        return ""
    best_slug, best_priority = "", None
    for entry in models:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("slug") or "")
        if not slug or entry.get("visibility") not in (None, "list"):
            continue
        haystack = f"{entry.get('description') or ''} {slug}".lower()
        if not any(marker in haystack for marker in BUDGET_MARKERS):
            continue
        priority = entry.get("priority")
        priority = priority if isinstance(priority, int) else 0
        if best_priority is None or priority > best_priority or (
            priority == best_priority and slug < best_slug
        ):
            best_slug, best_priority = slug, priority
    return best_slug


class CodexProvider:
    name = "codex"
    title = "Codex"

    def __init__(self, cfg: ProviderConfig, *, timeout: float = 20.0, ping_timeout: float = 180.0, workdir: Path | None = None):
        self.cfg = cfg
        self.timeout = timeout
        self.ping_timeout = ping_timeout
        self.workdir = Path(workdir or Path.home())
        self.auth_file = cfg.path("auth_file", DEFAULT_AUTH_FILE)
        self.codex_config = cfg.path("config_file", DEFAULT_CODEX_CONFIG)
        self.models_cache = cfg.path("models_cache", DEFAULT_MODELS_CACHE)
        self.model = str(cfg.get("model") or "")
        self.effort = str(cfg.get("effort") or "low")
        self.prompt = str(cfg.get("prompt") or "ok")
        self.bin = str(cfg.get("bin") or "codex")
        self._access_token: str | None = None

    # -- auth -------------------------------------------------------------- #

    def _read_auth(self) -> dict:
        try:
            return json.loads(Path(self.auth_file).read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"cannot read {self.auth_file}: {exc}") from None
        except ValueError:
            raise RuntimeError(f"{self.auth_file} is not valid JSON") from None

    def account_id(self) -> str | None:
        tokens = self._read_auth().get("tokens") or {}
        value = tokens.get("account_id")
        return value if isinstance(value, str) and value else None

    def token(self) -> str:
        if self._access_token:
            return self._access_token
        tokens = self._read_auth().get("tokens") or {}
        value = tokens.get("access_token")
        if not isinstance(value, str) or not value:
            raise RuntimeError(
                f"no Codex OAuth token in {self.auth_file} — run `codex login`"
            )
        self._access_token = value
        return value

    def refresh(self) -> str:
        """Exchange the refresh token, persisting rotated tokens for the CLI."""
        data = self._read_auth()
        tokens = data.get("tokens") or {}
        refresh_token = tokens.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise RuntimeError("Codex auth has no refresh token — run `codex login`")
        payload = request_json(
            OAUTH_TOKEN_URL,
            method="POST",
            body={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            },
            timeout=self.timeout,
        )
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise RuntimeError("Codex token refresh returned no access_token")
        tokens["access_token"] = access
        if payload.get("refresh_token"):
            tokens["refresh_token"] = payload["refresh_token"]
        if payload.get("id_token"):
            tokens["id_token"] = payload["id_token"]
        data["tokens"] = tokens
        data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp = Path(str(self.auth_file) + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.auth_file)
        self._access_token = access
        return access

    def base_url(self) -> str:
        configured = str(self.cfg.get("base_url") or "").strip()
        if not configured:
            try:
                import tomllib

                with Path(self.codex_config).open("rb") as fh:
                    configured = str((tomllib.load(fh) or {}).get("chatgpt_base_url") or "").strip()
            except (OSError, ValueError):
                configured = ""
        base = (configured or DEFAULT_BASE).rstrip("/")
        if "chatgpt.com" in base or "chat.openai.com" in base:
            if "/backend-api" not in base:
                base += "/backend-api"
        elif not configured:
            base = DEFAULT_BASE
        return base

    def _get_usage(self, token: str) -> dict:
        headers = {"Authorization": f"Bearer {token}"}
        account = self.account_id()
        if account:
            headers["chatgpt-account-id"] = account
        return request_json(f"{self.base_url()}/wham/usage", headers=headers, timeout=self.timeout)

    # -- provider interface ------------------------------------------------ #

    def usage(self) -> Usage:
        try:
            payload = self._get_usage(self.token())
        except HttpError as exc:
            if exc.status != 401:
                raise
            payload = self._get_usage(self.refresh())
        return parse_usage(payload)

    def ping_model(self) -> str:
        return self.model or cheapest_model(self.models_cache)

    def ping_command(self) -> list[str]:
        command = [
            self.bin,
            "exec",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            "--disable",
            "hooks",
            "--sandbox",
            "read-only",
            "-c",
            f"model_reasoning_effort={self.effort}",
        ]
        model = self.ping_model()
        if model:
            command += ["-m", model]
        command.append(self.prompt)
        return command

    def ping_mode(self) -> str:
        mode = str(self.cfg.get("ping_mode") or "cli").strip().lower()
        return mode if mode in ("api", "cli") else "cli"

    def ping(self) -> PingResult:
        """Trigger a window: over the CLI (rich, ~12k tokens) or the API (tiny)."""
        if self.ping_mode() != "api":
            return self._cli_ping()
        result = self._api_ping()
        if result.ok or not self.cfg.flag("ping_fallback", True):
            return result
        fallback = self._cli_ping()
        if fallback.ok:
            fallback.detail = f"api ping failed ({result.error}); fell back to codex exec"
            return fallback
        fallback.error = f"api: {result.error} | cli: {fallback.error}"
        return fallback

    def _api_ping(self) -> PingResult:
        """One raw Responses turn against the ChatGPT backend.

        This is the same endpoint the Codex CLI uses, so the request is billed
        against the subscription — but without the agent system prompt, which is
        what makes the CLI path cost ~12k input tokens per ping.
        """
        model = self.ping_model()
        if not model:
            return PingResult(
                ok=False,
                error="ping_mode=api needs a model: set providers.codex.model "
                "(the Codex catalog could not be read)",
            )
        body = {
            "model": model,
            "stream": True,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": self.prompt}],
                }
            ],
            "tools": [],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "reasoning": {"effort": self.effort},
            "store": False,
            "include": [],
            "max_output_tokens": API_MIN_OUTPUT_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "originator": CLI_ORIGINATOR,
            "User-Agent": f"{CLI_ORIGINATOR}/0.163.0",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }
        account = self.account_id()
        if account:
            headers["ChatGPT-Account-ID"] = account

        started = time.monotonic()
        try:
            events = self._post_responses(body, headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read(65536).decode("utf-8", errors="replace")
            if exc.code == 401:
                try:
                    headers["Authorization"] = f"Bearer {self.refresh()}"
                    events = self._post_responses(body, headers)
                except urllib.error.HTTPError as retry_exc:
                    return PingResult(
                        ok=False,
                        error=f"HTTP {retry_exc.code} after token refresh",
                        model=model,
                        seconds=time.monotonic() - started,
                    )
                except Exception as retry_exc:  # noqa: BLE001
                    return PingResult(ok=False, error=str(retry_exc), model=model)
            else:
                return PingResult(
                    ok=False,
                    error=_api_error_text(exc.code, detail),
                    model=model,
                    seconds=time.monotonic() - started,
                )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return PingResult(ok=False, error=f"{type(exc).__name__}: {exc}", model=model)

        input_tokens = output_tokens = None
        completed = False
        failure = None
        for event in events:
            kind = event.get("type")
            if kind == "response.completed":
                completed = True
                usage = event.get("usage")
                if not isinstance(usage, dict):
                    response = event.get("response")
                    usage = response.get("usage") if isinstance(response, dict) else {}
                if isinstance(usage, dict):
                    if isinstance(usage.get("input_tokens"), int):
                        input_tokens = usage["input_tokens"]
                    if isinstance(usage.get("output_tokens"), int):
                        output_tokens = usage["output_tokens"]
            elif kind in ("error", "response.failed"):
                failure = _event_error(event) or "request failed"

        elapsed = time.monotonic() - started
        if failure and not completed:
            return PingResult(ok=False, error=failure, model=model, seconds=elapsed)
        if not completed:
            return PingResult(
                ok=False,
                error="stream ended without response.completed",
                model=model,
                seconds=elapsed,
            )
        tokens = None
        if input_tokens is not None or output_tokens is not None:
            tokens = (input_tokens or 0) + (output_tokens or 0)
        return PingResult(ok=True, seconds=elapsed, model=model, tokens=tokens)

    def _post_responses(self, body: dict, headers: dict):
        """POST the Responses request and return an iterator of SSE events."""
        url = f"{self.base_url()}{RESPONSES_PATH}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body, separators=(",", ":")).encode(),
            method="POST",
        )
        for key, value in headers.items():
            request.add_header(key, value)
        request.add_header("session-id", str(uuid.uuid4()))
        request.add_header("thread-id", str(uuid.uuid4()))
        request.add_header("x-client-request-id", str(uuid.uuid4()))
        response = urllib.request.urlopen(request, timeout=self.ping_timeout)
        return _iter_sse(response)

    def _cli_ping(self) -> PingResult:
        binary = shutil.which(self.bin) or (self.bin if Path(self.bin).exists() else None)
        if not binary:
            return PingResult(ok=False, error=f"`{self.bin}` not found in PATH", model=self.ping_model() or None)
        command = self.ping_command()
        command[0] = binary
        started = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                cwd=str(self.workdir),
                capture_output=True,
                text=True,
                timeout=self.ping_timeout,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except subprocess.TimeoutExpired:
            return PingResult(ok=False, error=f"codex exec timed out after {self.ping_timeout:.0f}s")
        except OSError as exc:
            return PingResult(ok=False, error=f"cannot run codex: {exc}")
        elapsed = time.monotonic() - started
        tokens = _tokens_from_events(proc.stdout)
        if proc.returncode != 0:
            reason = (proc.stderr or proc.stdout or "").strip().splitlines()
            detail = reason[-1][:400] if reason else f"exit code {proc.returncode}"
            return PingResult(ok=False, error=detail, model=self.ping_model() or None, seconds=elapsed)
        return PingResult(
            ok=True,
            seconds=elapsed,
            model=self.ping_model() or None,
            tokens=tokens,
        )


def _iter_sse(stream) -> Iterator[dict]:
    """Yield JSON events from a Server-Sent-Events byte stream."""
    buffer: list[str] = []

    def flush():
        if not buffer:
            return None
        payload = "\n".join(buffer)
        buffer.clear()
        if payload == "[DONE]":
            return None
        try:
            event = json.loads(payload)
        except ValueError:
            return None
        return event if isinstance(event, dict) else None

    for raw in stream:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            event = flush()
            if event is not None:
                yield event
            continue
        if line.startswith(":") or line.startswith("event:"):
            continue
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())
    event = flush()
    if event is not None:
        yield event


def _api_error_text(code: int, detail: str) -> str:
    message = detail.strip()
    try:
        parsed = json.loads(detail)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and error.get("message"):
            message = str(error["message"])
        elif isinstance(error, str) and error:
            message = error
    return f"HTTP {code}: {message[:300]}"


def _event_error(event: dict) -> str | None:
    error = event.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    if isinstance(error, str) and error:
        return error[:300]
    response = event.get("response")
    if isinstance(response, dict):
        response_error = response.get("error")
        if isinstance(response_error, dict):
            return str(response_error.get("message") or response_error)[:300]
        if response.get("status") == "failed":
            return "response failed"
    return None


def _tokens_from_events(stdout: str) -> int | None:
    """Sum token counts from ``codex exec --json`` events."""
    total = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        usage = event.get("usage") if isinstance(event, dict) else None
        if not isinstance(usage, dict):
            continue
        value = usage.get("total_tokens")
        if isinstance(value, int):
            total = value
            continue
        parts = [usage.get(key) for key in ("input_tokens", "output_tokens")]
        numbers = [p for p in parts if isinstance(p, int)]
        if numbers:
            total = sum(numbers)
    return total


def build(cfg: ProviderConfig, *, general=None) -> CodexProvider:
    return CodexProvider(
        cfg,
        timeout=getattr(general, "read_timeout", 20.0),
        ping_timeout=getattr(general, "ping_timeout", 180.0),
        workdir=getattr(general, "workdir", Path.home()),
    )
