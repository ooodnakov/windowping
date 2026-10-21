"""Telegram transport: notifications and long polling, stdlib only."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from ..config import TelegramConfig
from ..http import USER_AGENT

API_ROOT = "https://api.telegram.org"
MAX_MESSAGE = 3800  # stay under Telegram's 4096-char limit


class TelegramError(RuntimeError):
    pass


def _call(token: str, method: str, payload: dict | None = None, timeout: float = 20.0) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{API_ROOT}/bot{token}/{method}", data=data,
                                     method="POST" if data else "GET")
    request.add_header("User-Agent", USER_AGENT)
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TelegramError(f"HTTP {exc.code}: {detail[:300]}") from None
    except urllib.error.URLError as exc:
        raise TelegramError(f"network error: {exc.reason}") from None
    if not body.get("ok"):
        raise TelegramError(str(body.get("description") or body))
    return body.get("result") or {}


def send_message(
    token: str,
    chat_id: int,
    text: str,
    *,
    silent: bool = False,
    parse_mode: str | None = "HTML",
) -> bool:
    text = text[:MAX_MESSAGE]

    def _send(body_text: str, mode: str | None) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": body_text,
            "disable_web_page_preview": True,
            "disable_notification": silent,
        }
        if mode:
            payload["parse_mode"] = mode
        return _call(token, "sendMessage", payload, timeout=20.0)

    try:
        _send(text, parse_mode)
    except TelegramError as exc:
        # A malformed entity must not swallow the notification: degrade to text.
        if "entit" not in str(exc).lower() and "parse" not in str(exc).lower():
            raise
        from ..render import strip_tags

        _send(strip_tags(text)[:MAX_MESSAGE], None)
    return True


class TelegramNotifier:
    """Sends transition messages; stays silent unless the event is enabled."""

    def __init__(self, cfg: TelegramConfig):
        self.cfg = cfg
        self.token = cfg.resolve_token()

    @property
    def active(self) -> bool:
        return bool(self.cfg.enabled and self.token and self.cfg.chat_id is not None)

    def notify(self, event: str, text: str) -> None:
        if not self.active or event not in self.cfg.notify_events:
            return
        chat_id = self.cfg.chat_id
        if chat_id is None:
            return
        try:
            send_message(self.token, int(chat_id), text, silent=self.cfg.silent)
        except TelegramError as exc:  # pragma: no cover - transport noise
            print(f"telegram notify failed: {exc}", flush=True)


class TelegramPoller:
    """Long-poll ``getUpdates`` and hand text messages to a callback."""

    def __init__(self, cfg: TelegramConfig, on_message):
        self.cfg = cfg
        self.token = cfg.resolve_token()
        self.on_message = on_message
        self._offset: int | None = None

    def allowed(self, chat_id: int) -> bool:
        allowed = self.cfg.allow_chat_ids or ((self.cfg.chat_id,) if self.cfg.chat_id else ())
        return chat_id in allowed

    def reply(self, chat_id: int, text: str) -> None:
        try:
            send_message(self.token, chat_id, text)
        except TelegramError as exc:  # pragma: no cover - transport noise
            print(f"telegram reply failed: {exc}", flush=True)

    def poll_forever(self, stop_event=None) -> None:  # pragma: no cover - network loop
        while not (stop_event and stop_event.is_set()):
            try:
                updates = _call(
                    self.token,
                    "getUpdates",
                    {"offset": self._offset, "timeout": 45, "allowed_updates": ["message"]},
                    timeout=60.0,
                )
            except TelegramError as exc:
                print(f"telegram poll failed: {exc}", flush=True)
                time.sleep(5)
                continue
            items = updates if isinstance(updates, list) else []
            for update in items:
                self._offset = int(update.get("update_id", 0)) + 1
                message = update.get("message") or {}
                chat_id = (message.get("chat") or {}).get("id")
                text = (message.get("text") or "").strip()
                if not chat_id or not text or not self.allowed(int(chat_id)):
                    continue
                try:
                    answer = self.on_message(text)
                except Exception as exc:  # noqa: BLE001 - one bad command must not stop the bot
                    answer = f"ошибка: {exc}"
                if answer:
                    self.reply(int(chat_id), answer)
