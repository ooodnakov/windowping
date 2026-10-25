"""The one live card.

A watcher that reports every transition produces a wall of messages; the useful
view is one message that keeps itself current. The card is sent once, then edited
in place by the tick, by the buttons, and by the refresh button.

Telegram edits are cheap but not free: an edit that changes nothing is skipped by
Telegram itself (`message is not modified`), and the card only carries the numbers
the tick already has.
"""

from __future__ import annotations

import time

from .config import TelegramConfig
from .i18n import t
from .notify.telegram import delete_message, edit_message, pin_message, send_message
from .providers.base import Usage
from .render import fmt_ts, telegram_status


def keyboard(lang: str = "en") -> dict:
    """Inline keyboard under the card: refresh, ping, stats, schedule, mute."""
    return {
        "inline_keyboard": [
            [
                {"text": t(lang, "btn_refresh"), "callback_data": "refresh"},
                {"text": t(lang, "btn_ping"), "callback_data": "ping"},
            ],
            [
                {"text": t(lang, "btn_stats"), "callback_data": "stats"},
                {"text": t(lang, "btn_schedule"), "callback_data": "schedule"},
            ],
            [
                {"text": t(lang, "btn_new"), "callback_data": "new"},
                {"text": t(lang, "btn_mute"), "callback_data": "mute"},
            ],
        ]
    }


def render(
    rows: list[tuple[str, Usage | None, str | None]],
    now: float | None = None,
    *,
    lang: str = "en",
    updated_at: float | None = None,
    next_at: float | None = None,
    muted_until: float | None = None,
) -> str:
    """Card body: the usual status blocks plus a one-line footer."""
    now = now if now is not None else time.time()
    body = telegram_status(rows, now, header=t(lang, "card_title"), lang=lang)
    footer = t(
        lang,
        "card_footer",
        updated=fmt_ts(updated_at) if updated_at else "—",
        **{"next": fmt_ts(next_at) if next_at else "—"},
    )
    lines = [body, footer]
    if muted_until and muted_until > now:
        lines.append(t(lang, "card_footer_muted", until=fmt_ts(muted_until)))
    return "\n".join(lines)


class CardPublisher:
    """Keep exactly one card message alive: send once, edit afterwards."""

    def __init__(self, cfg: TelegramConfig, state):
        self.cfg = cfg
        self.state = state
        self.token = cfg.resolve_token()
        self._last_text: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.cfg.enabled and self.token and self.cfg.chat_id is not None)

    def publish(self, text: str, lang: str = "en", *, silent: bool = True) -> bool:
        chat_id = self.cfg.chat_id
        if not self.active or chat_id is None:
            return False
        if text == self._last_text:
            return True
        markup = keyboard(lang)
        message_id = self.state.data.get("card_message_id")
        if message_id:
            if edit_message(self.token, int(chat_id), int(message_id), text, reply_markup=markup):
                self._last_text = text
                return True
            # The message may have been deleted by hand; fall through and resend.
        sent = send_message(self.token, int(chat_id), text, silent=silent, reply_markup=markup)
        if sent:
            self.state.data["card_message_id"] = sent
            self.state.save()
            self._last_text = text
            # Pinned cards stay visible while the chat grows around them.
            pin_message(self.token, int(chat_id), sent)
            return True
        return False

    def recreate(self, text: str, lang: str = "en") -> bool:
        """Drop the old card and put a fresh one at the bottom of the chat."""
        chat_id = self.cfg.chat_id
        if not self.active or chat_id is None:
            return False
        old = self.state.data.get("card_message_id")
        if old:
            delete_message(self.token, int(chat_id), int(old))
            self.state.data.pop("card_message_id", None)
        self._last_text = None
        return self.publish(text, lang, silent=True)
