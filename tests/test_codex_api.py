import unittest

from windowping.config import ProviderConfig
from windowping.providers import codex


SSE = (
    b'event: response.created\n'
    b'data: {"type":"response.created","response":{"id":"resp_1"}}\n'
    b'\n'
    b'event: response.output_text.delta\n'
    b'data: {"type":"response.output_text.delta","delta":"OK"}\n'
    b'\n'
    b'event: response.completed\n'
    b'data: {"type":"response.completed","response":{"usage":{"input_tokens":11,"output_tokens":5}}}\n'
    b'\n'
    b'data: [DONE]\n'
    b'\n'
)


class IterSseTest(unittest.TestCase):
    def test_parses_events_and_skips_done(self):
        events = list(codex._iter_sse(iter(SSE.splitlines(keepends=True))))
        types = [e.get("type") for e in events]
        self.assertEqual(types, ["response.created", "response.output_text.delta", "response.completed"])
        self.assertNotIn("[DONE]", types)

    def test_multi_line_data_is_joined(self):
        stream = [
            b'data: {"type":"response.completed",\n',
            b'data: "usage":{"input_tokens":3,"output_tokens":1}}\n',
            b'\n',
        ]
        events = list(codex._iter_sse(stream))
        self.assertEqual(events[0]["usage"]["output_tokens"], 1)

    def test_garbage_is_ignored(self):
        stream = [b'data: not-json\n', b'\n', b'event: ping\n', b'\n']
        self.assertEqual(list(codex._iter_sse(stream)), [])


class ErrorHelpersTest(unittest.TestCase):
    def test_api_error_text_extracts_message(self):
        detail = '{"error":{"message":"Invalid max_output_tokens","type":"invalid_request_error"}}'
        text = codex._api_error_text(400, detail)
        self.assertIn("HTTP 400", text)
        self.assertIn("Invalid max_output_tokens", text)

    def test_event_error_shapes(self):
        self.assertEqual(
            codex._event_error({"type": "error", "error": {"message": "boom"}}), "boom"
        )
        self.assertEqual(
            codex._event_error({"type": "response.failed", "response": {"status": "failed"}}),
            "response failed",
        )
        self.assertIsNone(codex._event_error({"type": "response.completed"}))


class ModeDispatchTest(unittest.TestCase):
    def provider(self, **options) -> codex.CodexProvider:
        return codex.CodexProvider(ProviderConfig(name="codex", options=options))

    def test_default_is_cli(self):
        self.assertEqual(self.provider().ping_mode(), "cli")

    def test_unknown_mode_falls_back_to_cli(self):
        self.assertEqual(self.provider(ping_mode="carrier-pigeon").ping_mode(), "cli")

    def test_api_mode_uses_api(self):
        class Recording(codex.CodexProvider):
            calls: list

            def _api_ping(self):
                self.calls.append("api")
                return codex.PingResult(ok=True, model="m", tokens=16)

            def _cli_ping(self):
                self.calls.append("cli")
                return codex.PingResult(ok=True, model="m", tokens=11971)

        provider = Recording(ProviderConfig(name="codex", options={"ping_mode": "api"}))
        provider.calls = []
        result = provider.ping()
        self.assertEqual(provider.calls, ["api"])
        self.assertEqual(result.tokens, 16)

    def test_api_failure_falls_back_to_cli(self):
        class Failing(codex.CodexProvider):
            calls: list

            def _api_ping(self):
                self.calls.append("api")
                return codex.PingResult(ok=False, error="HTTP 404")

            def _cli_ping(self):
                self.calls.append("cli")
                return codex.PingResult(ok=True, model="m", tokens=11971)

        provider = Failing(ProviderConfig(name="codex", options={"ping_mode": "api"}))
        provider.calls = []
        result = provider.ping()
        self.assertEqual(provider.calls, ["api", "cli"])
        self.assertTrue(result.ok)
        self.assertIn("fell back", result.detail or "")

    def test_fallback_can_be_disabled(self):
        class Failing(codex.CodexProvider):
            calls: list

            def _api_ping(self):
                self.calls.append("api")
                return codex.PingResult(ok=False, error="HTTP 404")

            def _cli_ping(self):
                self.calls.append("cli")
                return codex.PingResult(ok=True, model="m")

        provider = Failing(
            ProviderConfig(name="codex", options={"ping_mode": "api", "ping_fallback": False})
        )
        provider.calls = []
        result = provider.ping()
        self.assertEqual(provider.calls, ["api"])
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
