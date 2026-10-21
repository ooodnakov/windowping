import datetime as dt
import unittest
from unittest import mock

from windowping.config import TelegramConfig
from windowping.notify import telegram
from windowping.quiet import describe, in_quiet_hours, parse_ranges


def at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 10, 22, hour, minute)


class ParseTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_ranges(""), [])
        self.assertEqual(parse_ranges(None), [])
        self.assertEqual(parse_ranges("   "), [])

    def test_wrapping_range(self):
        self.assertEqual(
            parse_ranges("12:00-08:00"),
            [(dt.time(12, 0), dt.time(8, 0))],
        )

    def test_several_ranges_and_loose_spacing(self):
        self.assertEqual(
            parse_ranges(" 23:30 - 7:05 , 13:00-14:00 "),
            [(dt.time(23, 30), dt.time(7, 5)), (dt.time(13, 0), dt.time(14, 0))],
        )

    def test_garbage_raises(self):
        for spec in ("12-8", "noon", "25:00-08:00", "12:60-08:00", "12:00..08:00"):
            with self.assertRaises(ValueError, msg=spec):
                parse_ranges(spec)


class InsideTest(unittest.TestCase):
    def test_no_spec_is_never_quiet(self):
        self.assertFalse(in_quiet_hours("", at(3)))

    def test_wrapping_window(self):
        spec = "12:00-08:00"
        self.assertTrue(in_quiet_hours(spec, at(12, 0)))   # boundary included
        self.assertTrue(in_quiet_hours(spec, at(23, 59)))
        self.assertTrue(in_quiet_hours(spec, at(0, 30)))
        self.assertTrue(in_quiet_hours(spec, at(7, 59)))
        self.assertFalse(in_quiet_hours(spec, at(8, 0)))   # end is exclusive
        self.assertFalse(in_quiet_hours(spec, at(11, 59)))

    def test_plain_window(self):
        spec = "13:00-14:00"
        self.assertTrue(in_quiet_hours(spec, at(13, 30)))
        self.assertFalse(in_quiet_hours(spec, at(12, 59)))
        self.assertFalse(in_quiet_hours(spec, at(14, 0)))

    def test_second_range_wraps(self):
        spec = "09:00-10:00,22:00-06:00"
        self.assertTrue(in_quiet_hours(spec, at(9, 15)))
        self.assertTrue(in_quiet_hours(spec, at(2, 0)))
        self.assertFalse(in_quiet_hours(spec, at(12, 0)))

    def test_equal_bounds_mean_never(self):
        self.assertFalse(in_quiet_hours("12:00-12:00", at(12, 0)))

    def test_describe(self):
        self.assertEqual(describe(""), "off")
        self.assertEqual(describe("12:00-08:00"), "12:00-08:00")


class TransportTest(unittest.TestCase):
    def cfg(self, *, silent: bool = False, quiet_hours: str = "") -> TelegramConfig:
        return TelegramConfig(
            enabled=True,
            bot_token="t",
            chat_id=1,
            silent=silent,
            quiet_hours=quiet_hours,
        )

    def test_notifier_is_silent_during_quiet_hours(self):
        notifier = telegram.TelegramNotifier(self.cfg(quiet_hours="12:00-08:00"))
        with mock.patch.object(telegram, "send_message") as sent, mock.patch.object(
            telegram.TelegramConfig, "in_quiet_hours", return_value=True
        ):
            notifier.notify("ping", "hello")
        self.assertTrue(sent.call_args.kwargs["silent"])

    def test_notifier_is_loud_outside_quiet_hours(self):
        notifier = telegram.TelegramNotifier(self.cfg(quiet_hours="12:00-08:00"))
        with mock.patch.object(telegram, "send_message") as sent, mock.patch.object(
            telegram.TelegramConfig, "in_quiet_hours", return_value=False
        ):
            notifier.notify("ping", "hello")
        self.assertFalse(sent.call_args.kwargs["silent"])

    def test_reply_follows_quiet_hours_too(self):
        poller = telegram.TelegramPoller(self.cfg(quiet_hours="12:00-08:00"), lambda text, lang=None: "x")
        with mock.patch.object(telegram, "send_message") as sent, mock.patch.object(
            telegram.TelegramConfig, "in_quiet_hours", return_value=True
        ):
            poller.reply(1, "answer")
        self.assertTrue(sent.call_args.kwargs["silent"])

    def test_silent_flag_still_forces_silence(self):
        notifier = telegram.TelegramNotifier(self.cfg(silent=True))
        with mock.patch.object(telegram, "send_message") as sent:
            notifier.notify("ping", "hello")
        self.assertTrue(sent.call_args.kwargs["silent"])

    def test_config_rejects_a_broken_spec(self):
        with self.assertRaises(ValueError):
            parse_ranges("12:00-08:00, garbage")


if __name__ == "__main__":
    unittest.main()
