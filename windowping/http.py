"""Tiny urllib wrapper: JSON in, JSON out, useful error text out."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

USER_AGENT = "windowping/0.1.0"


class HttpError(RuntimeError):
    def __init__(self, status: int, message: str, url: str = ""):
        self.status = status
        self.message = message
        self.url = url
        super().__init__(f"HTTP {status}: {message}")


def _error_message(raw: str) -> str:
    text = raw.strip()
    if not text:
        return "empty response"
    try:
        parsed = json.loads(text)
    except ValueError:
        return text[:300]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and error.get("message"):
            code = error.get("code")
            return f"{error['message']}" + (f" (code {code})" if code else "")
        if isinstance(error, str) and error:
            return error
        for key in ("message", "msg", "detail"):
            if parsed.get(key):
                return str(parsed[key])
    return text[:300]


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    body: dict | None = None,
    timeout: float = 20.0,
) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        if value is not None:
            request.add_header(key, str(value))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HttpError(exc.code, _error_message(detail), url) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error: {exc.reason}") from None
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError(f"non-JSON response from {url}: {raw[:200]!r}") from None
