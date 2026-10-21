import unittest

from windowping.providers.base import Usage, Window
from windowping.render import (
    HELP_HTML,
    help_html,
    bar_bare,
    fmt_delta,
    fmt_tokens,
    message_error,
    message_ping,
    message_ping_failed,
    message_recovered,
    message_weekly,
    strip_tags,
    telegram_status,
)

NOW = 1_800_000_000.0


def usage(*, plan: str | None = None, details: list[str] | None = None,
          five: Window | None = None, weekly: Window | None = None,
          provider: str = "codex") -> Usage:
    return Usage(
        provider=provider,
        five=five if five is not None else Window(pct=69, reset_at=NOW + 3600),
        weekly=weekly if weekly is not None else Window(pct=30, reset_at=NOW + 604800),
        plan=plan,
        details=details or [],
    )


class PrimitivesTest(unittest.TestCase):
    def test_delta(self):
        self.assertEqual(fmt_delta(60), "1m00s")
        self.assertEqual(fmt_delta(3700), "1h01m")
        self.assertEqual(fmt_delta(90000), "1d1h")
        self.assertEqual(fmt_delta(None), "—")

    def test_tokens(self):
        self.assertEqual(fmt_tokens(14), "14 tok")
        self.assertEqual(fmt_tokens(11971), "12.0k tok")
        self.assertEqual(fmt_tokens(None), "—")

    def test_bar_bare(self):
        self.assertEqual(bar_bare(0, 4), "░░░░")
        self.assertEqual(bar_bare(100, 4), "████")
        self.assertEqual(len(bar_bare(55, 10)), 10)


class TelegramStatusTest(unittest.TestCase):
    def test_layout(self):
        text = telegram_status([("codex", usage(plan="plus"), None)], NOW)
        self.assertIn("<b>codex</b>", text)
        self.assertIn("<i>plus</i>", text)
        self.assertIn("🟢", text)
        self.assertIn("<pre>", text)
        # 5h and weekly rows, both with bars and countdowns
        self.assertIn("5h     ", text)
        self.assertIn("weekly ", text)
        self.assertIn("1h00m", text)

    def test_weekly_exhausted_is_orange(self):
        text = telegram_status(
            [("glm", usage(weekly=Window(pct=100, reset_at=NOW + 60, exceeded=True)), None)], NOW
        )
        self.assertIn("🟠", text)

    def test_error_is_red_and_escaped(self):
        text = telegram_status([("codex", None, "HTTP 401: <bad & ugly>")], NOW)
        self.assertIn("🔴", text)
        self.assertIn("&lt;bad &amp; ugly&gt;", text)

    def test_header(self):
        text = telegram_status([("codex", usage(), None)], NOW, header="limits")
        self.assertTrue(text.startswith("<b>limits</b>"))

    def test_details_are_deduplicated(self):
        text = telegram_status(
            [
                (
                    "codex",
                    usage(details=["3 reset credit(s) available", "5h $1 of $2"]),
                    None,
                )
            ],
            NOW,
        )
        self.assertIn("3 reset credit(s) available", text)
        self.assertNotIn("$1 of $2", text)  # bar duplicate dropped

    def test_unenforced_window(self):
        text = telegram_status(
            [("codex", usage(five=Window(enforced=False)), None)], NOW
        )
        self.assertIn("no limit", text)


class RussianTest(unittest.TestCase):
    """Russian is the only localized surface; everything else is English."""

    def test_status_ru(self):
        text = telegram_status(
            [("codex", usage(plan="plus", details=["3 reset credit(s) available"]), None)],
            NOW,
            header="лимиты",
            lang="ru",
        )
        self.assertTrue(text.startswith("<b>лимиты</b>"))
        self.assertIn("3 сброс(а) в запасе", text)

    def test_no_limit_ru(self):
        text = telegram_status([("codex", usage(five=Window(enforced=False)), None)], NOW, lang="ru")
        self.assertIn("нет лимита", text)

    def test_messages_ru(self):
        self.assertIn("новое окно", message_ping("Codex", "m", 16, 1.2, lang="ru"))
        self.assertIn("5h-окно до", message_ping("Codex", None, None, None, reset_at=NOW, lang="ru"))
        self.assertIn("пинг не прошёл", message_ping_failed("Codex", "boom", lang="ru"))
        self.assertIn("недельный лимит выбран", message_weekly("GLM", 100, None, NOW, lang="ru"))
        self.assertIn("ошибка чтения лимитов", message_error("GLM", "boom", lang="ru"))
        self.assertIn("снова на связи", message_recovered("GLM", lang="ru"))

    def test_help_ru(self):
        text = help_html("ru")
        self.assertIn("Команды", text)
        self.assertIn("/status", text)
        self.assertIn("Обозначения", text)

    def test_monthly_detail_ru(self):
        text = telegram_status(
            [("commandcode", usage(details=["$46.27 monthly credits left"]), None)],
            NOW,
            lang="ru",
        )
        self.assertIn("на месяц осталось $46.27", text)


class MessageTest(unittest.TestCase):
    def test_ping(self):
        text = message_ping("Codex", "gpt-5.6-luna", 11971, 6.9)
        self.assertIn("✅ <b>Codex</b>", text)
        self.assertIn("<code>gpt-5.6-luna</code>", text)
        self.assertIn("12.0k tok", text)
        self.assertIn("6.9s", text)

    def test_ping_with_reset(self):
        text = message_ping("Codex", None, None, None, reset_at=NOW)
        self.assertIn("5h window until", text)

    def test_weekly(self):
        text = message_weekly("GLM", 100, None)
        self.assertIn("⛔️ <b>GLM</b>", text)
        self.assertIn("100%", text)

    def test_failures_escaped(self):
        for text in (
            message_error("X", "<boom>"),
            message_ping_failed("X", "<boom>"),
        ):
            self.assertIn("&lt;boom&gt;", text)


class HelpAndFallbackTest(unittest.TestCase):
    def test_help_mentions_commands(self):
        for command in ("/status", "/ping", "/help"):
            self.assertIn(command, HELP_HTML)

    def test_help_defaults_to_english(self):
        self.assertIn("Commands", HELP_HTML)
        self.assertNotIn("Команды", HELP_HTML)

    def test_strip_tags(self):
        plain = strip_tags("✅ <b>X</b> — <pre>a &lt; b</pre>")
        self.assertEqual(plain, "✅ X — a < b")


if __name__ == "__main__":
    unittest.main()
