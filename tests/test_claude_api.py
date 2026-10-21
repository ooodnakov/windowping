import unittest

from windowping.config import ProviderConfig
from windowping.providers import claude as claude_mod
from windowping.providers.base import PingResult


class ApiPingShapeTest(unittest.TestCase):
    def test_payload_is_one_token(self):
        body = claude_mod.api_ping_payload("claude-haiku-4-5", "ok")
        self.assertEqual(body["max_tokens"], 1)
        self.assertEqual(body["model"], "claude-haiku-4-5")
        self.assertEqual(body["messages"], [{"role": "user", "content": "ok"}])

    def test_headers_look_like_the_cli(self):
        headers = claude_mod.api_ping_headers("tok", "2.1.112")
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(headers["anthropic-beta"], "oauth-2025-04-20")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["User-Agent"], "claude-code/2.1.112")
        # The OAuth beta replaces the API key; no x-api-key must sneak in.
        self.assertNotIn("x-api-key", {k.lower() for k in headers})


class LimitsFromHeadersTest(unittest.TestCase):
    def test_reads_both_fields(self):
        pct, reset = claude_mod.limits_from_headers(
            {
                "anthropic-ratelimit-unified-5h-utilization": "12.5",
                "anthropic-ratelimit-unified-5h-reset": "1792601525",
            }
        )
        self.assertEqual(pct, 12.5)
        self.assertEqual(reset, 1792601525.0)

    def test_missing_headers_are_none(self):
        self.assertEqual(claude_mod.limits_from_headers({}), (None, None))
        self.assertEqual(
            claude_mod.limits_from_headers({"anthropic-ratelimit-unified-5h-utilization": ""}),
            (None, None),
        )


class ModeDispatchTest(unittest.TestCase):
    def provider(self, **options) -> claude_mod.ClaudeProvider:
        return claude_mod.ClaudeProvider(ProviderConfig(name="claude", options=options))

    def test_default_is_cli(self):
        self.assertEqual(self.provider().ping_mode, "cli")

    def test_unknown_mode_falls_back_to_cli(self):
        self.assertEqual(self.provider(ping_mode="telepathy").ping_mode, "cli")

    def test_api_mode_calls_api_only(self):
        class Recording(claude_mod.ClaudeProvider):
            calls: list

            def _api_ping(self):
                self.calls.append("api")
                return PingResult(ok=True, model="m", tokens=2)

            def _cli_ping(self):
                self.calls.append("cli")
                return PingResult(ok=True, model="m", tokens=2)

        provider = Recording(ProviderConfig(name="claude", options={"ping_mode": "api"}))
        provider.calls = []
        result = provider.ping()
        self.assertEqual(provider.calls, ["api"])
        self.assertTrue(result.ok)

    def test_api_failure_falls_back_to_cli(self):
        class Failing(claude_mod.ClaudeProvider):
            calls: list

            def _api_ping(self):
                self.calls.append("api")
                return PingResult(ok=False, error="HTTP 403")

            def _cli_ping(self):
                self.calls.append("cli")
                return PingResult(ok=True, model="m", tokens=9)

        provider = Failing(ProviderConfig(name="claude", options={"ping_mode": "api"}))
        provider.calls = []
        result = provider.ping()
        self.assertEqual(provider.calls, ["api", "cli"])
        self.assertTrue(result.ok)
        self.assertIn("fell back", result.detail or "")

    def test_fallback_can_be_disabled(self):
        class Failing(claude_mod.ClaudeProvider):
            calls: list

            def _api_ping(self):
                self.calls.append("api")
                return PingResult(ok=False, error="HTTP 403")

            def _cli_ping(self):
                self.calls.append("cli")
                return PingResult(ok=True)

        provider = Failing(
            ProviderConfig(name="claude", options={"ping_mode": "api", "ping_fallback": False})
        )
        provider.calls = []
        self.assertFalse(provider.ping().ok)
        self.assertEqual(provider.calls, ["api"])

    def test_api_model_default(self):
        self.assertEqual(self.provider().api_model, claude_mod.DEFAULT_API_MODEL)
        self.assertEqual(self.provider(api_model="claude-sonnet-4-5").api_model, "claude-sonnet-4-5")


if __name__ == "__main__":
    unittest.main()
