import http.client
import unittest
from unittest import mock

from windowping.config import TelegramConfig
from windowping.notify import telegram


class CallErrorMappingTest(unittest.TestCase):
    def test_remote_disconnect_becomes_a_telegram_error(self):
        with mock.patch.object(
            telegram.urllib.request,
            "urlopen",
            side_effect=http.client.RemoteDisconnected("Remote end closed connection"),
        ):
            with self.assertRaises(telegram.TelegramError) as ctx:
                telegram._call("token", "getUpdates")
        self.assertIn("transport error", str(ctx.exception))

    def test_socket_timeout_becomes_a_telegram_error(self):
        with mock.patch.object(telegram.urllib.request, "urlopen", side_effect=TimeoutError("slow")):
            with self.assertRaises(telegram.TelegramError):
                telegram._call("token", "getUpdates")

    def test_urlerror_is_mapped(self):
        err = telegram.urllib.error.URLError("dns")
        with mock.patch.object(telegram.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(telegram.TelegramError) as ctx:
                telegram._call("token", "getUpdates")
        self.assertIn("network error", str(ctx.exception))


class _Stop:
    """Stop event that flips after N checks, so the loop can be tested."""

    def __init__(self, allow: int):
        self.allow = allow
        self.checks = 0

    def is_set(self) -> bool:
        self.checks += 1
        return self.checks > self.allow


class PollLoopTest(unittest.TestCase):
    def poller(self, on_message=lambda text, lang=None: "ok") -> telegram.TelegramPoller:
        cfg = TelegramConfig(enabled=True, bot_token="t", chat_id=1)
        return telegram.TelegramPoller(cfg, on_message)

    def test_transport_error_does_not_stop_the_loop(self):
        poller = self.poller()
        calls = []

        def fake_call(token, method, payload=None, timeout=20.0):
            calls.append(method)
            if len(calls) == 1:
                raise telegram.TelegramError("transport error: RemoteDisconnected")
            return []

        with mock.patch.object(telegram, "_call", side_effect=fake_call), mock.patch.object(
            telegram.time, "sleep"
        ) as slept:
            poller.poll_forever(stop_event=_Stop(allow=2))

        self.assertEqual(len(calls), 2, "the loop must poll again after a transport error")
        slept.assert_called()  # backoff happened

    def test_unexpected_exception_does_not_stop_the_loop(self):
        poller = self.poller()
        calls = []

        def fake_call(token, method, payload=None, timeout=20.0):
            calls.append(method)
            if len(calls) == 1:
                raise ValueError("weird thing")
            return []

        with mock.patch.object(telegram, "_call", side_effect=fake_call), mock.patch.object(
            telegram.time, "sleep"
        ):
            poller.poll_forever(stop_event=_Stop(allow=2))

        self.assertEqual(len(calls), 2)

    def test_broken_update_is_skipped_and_offset_advances(self):
        poller = self.poller(on_message=mock.Mock(side_effect=RuntimeError("boom")))
        updates = [
            {"update_id": 10, "message": {"chat": {"id": 1}, "text": "/status", "from": {}}},
            {"update_id": 11, "message": {"chat": {"id": 1}, "text": "/help", "from": {}}},
        ]
        replies = []
        poller.reply = lambda chat_id, text: replies.append(text)  # type: ignore[assignment]

        seen = []

        def fake_call(token, method, payload=None, timeout=20.0):
            seen.append(payload)
            return updates if len(seen) == 1 else []

        with mock.patch.object(telegram, "_call", side_effect=fake_call), mock.patch.object(
            telegram.time, "sleep"
        ):
            poller.poll_forever(stop_event=_Stop(allow=2))

        # Both updates produced an error reply instead of killing the poller.
        self.assertEqual(len(replies), 2)
        self.assertTrue(all("boom" in reply for reply in replies))
        self.assertEqual(poller._offset, 12)


if __name__ == "__main__":
    unittest.main()
