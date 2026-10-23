"""Tiny urllib wrapper: JSON in, JSON out, useful error text out."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import __version__

USER_AGENT = f"windowping/{__version__}"


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
    payload, _ = request_json_response(
        url, method=method, headers=headers, body=body, timeout=timeout
    )
    return payload


def request_json_response(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    body: dict | None = None,
    timeout: float = 20.0,
) -> tuple[dict, dict[str, str]]:
    """Like ``request_json`` but also returns the response headers, lowercased.

    Some providers only expose rate-limit state in their headers (Anthropic ships
    ``anthropic-ratelimit-unified-*`` on every message response), so a call has to
    be able to read them.
    """
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
            response_headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HttpError(exc.code, _error_message(detail), url) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error: {exc.reason}") from None
    if not raw.strip():
        return {}, response_headers
    try:
        return json.loads(raw), response_headers
    except ValueError:
        raise RuntimeError(f"non-JSON response from {url}: {raw[:200]!r}") from None
