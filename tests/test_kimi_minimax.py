import datetime as dt
import unittest
from unittest import mock

from windowping.config import ProviderConfig
from windowping.http import HttpError
from windowping.providers import kimi, minimax


def at(hour: int, minute: int = 0) -> float:
    return dt.datetime(2026, 10, 23, hour, minute, tzinfo=dt.timezone.utc).timestamp()


class KimiUsageTest(unittest.TestCase):
    def payload(self):
        return {
            "data": {
                "plan": "coding",
                "usages": [
                    {"window": {"duration": 5, "timeUnit": "hour"}, "used": 120,
                     "limit": 1000, "resetTime": "2026-10-23T18:00:00Z"},
                    {"window": {"duration": 7, "timeUnit": "day"}, "used": 3000,
                     "limit": 10000, "resetTime": 1792000000000},
                    {"window": {"duration": 30, "timeUnit": "day"}, "used": 9000,
                     "limit": 50000},
                ],
            }
        }

    def test_windows_are_identified_by_their_length(self):
        usage = kimi.parse_usage(self.payload())
        self.assertAlmostEqual(usage.five.pct, 12.0)
        self.assertAlmostEqual(usage.weekly.pct, 30.0)
        self.assertEqual(usage.plan, "coding")
        self.assertAlmostEqual(usage.five.reset_at or 0, at(18))
        self.assertAlmostEqual(usage.weekly.reset_at or 0, 1792000000.0)

    def test_monthly_window_lands_in_details(self):
        usage = kimi.parse_usage(self.payload())
        self.assertTrue(any("720h window" in line or "30h window" in line for line in usage.details))

    def test_flat_window_fields_are_accepted(self):
        payload = {"data": {"usages": [
            {"duration": 5, "timeUnit": "hours", "percentage": 42.5, "resetTime": 1792000000},
        ]}}
        usage = kimi.parse_usage(payload)
        self.assertAlmostEqual(usage.five.pct, 42.5)

    def test_missing_payload_raises(self):
        with self.assertRaises(RuntimeError):
            kimi.parse_usage({"data": {}})

    def test_exhausted_five_hour_window_is_marked(self):
        payload = {"data": {"usages": [
            {"window": {"duration": 5, "timeUnit": "hour"}, "used": 1000, "limit": 1000},
        ]}}
        self.assertTrue(kimi.parse_usage(payload).five.exceeded)


class KimiTransportTest(unittest.TestCase):
    def provider(self, **options) -> kimi.KimiProvider:
        return kimi.KimiProvider(ProviderConfig(name="kimi", options={"api_key": "k", **options}))

    def test_ping_uses_the_coding_base_and_counts_tokens(self):
        provider = self.provider(model="kimi-k2")
        response = {"model": "kimi-k2", "usage": {"total_tokens": 9}}
        with mock.patch.object(kimi, "request_json", return_value=response) as sent:
            result = provider.ping()
        self.assertTrue(result.ok)
        self.assertEqual(result.tokens, 9)
        self.assertEqual(sent.call_args.args[0], "https://api.kimi.com/coding/v1/chat/completions")
        self.assertEqual(sent.call_args.kwargs["body"]["max_tokens"], 1)

    def test_ping_reports_http_errors(self):
        provider = self.provider()
        with mock.patch.object(kimi, "request_json", side_effect=HttpError(401, "unauthorized")):
            result = provider.ping()
        self.assertFalse(result.ok)
        self.assertIn("401", result.error or "")

    def test_usage_sends_the_bearer_token(self):
        provider = self.provider()
        payload = {"data": {"usages": [{"window": {"duration": 5, "timeUnit": "hour"},
                                        "used": 1, "limit": 10}]}}
        with mock.patch.object(kimi, "request_json", return_value=payload) as sent:
            usage = provider.usage()
        self.assertAlmostEqual(usage.five.pct, 10.0)
        self.assertEqual(sent.call_args.kwargs["headers"]["Authorization"], "Bearer k")

    def test_missing_key_is_reported(self):
        provider = kimi.KimiProvider(ProviderConfig(name="kimi", options={}))
        with mock.patch.dict("os.environ", {"KIMI_API_KEY": ""}, clear=False):
            with self.assertRaises(RuntimeError):
                provider.api_key()


class MiniMaxUsageTest(unittest.TestCase):
    def payload(self):
        return {
            "data": {
                "model_remains": [
                    {
                        "model_name": "MiniMax-M2",
                        "start_time": 1792000000000,
                        "end_time": 1792018000000,
                        "current_interval_total_count": 1500,
                        "current_interval_usage_count": 300,
                    }
                ]
            }
        }

    def test_five_hour_block_from_start_and_end(self):
        usage = minimax.parse_usage(self.payload())
        self.assertAlmostEqual(usage.five.pct, 20.0)
        self.assertAlmostEqual(usage.five.reset_at or 0, 1792018000.0)

    def test_weekly_block_is_recognised(self):
        payload = {"model_remains": [
            {"start_time": 1792000000000, "end_time": 1792000000000 + 7 * 86400 * 1000,
             "current_interval_total_count": 100, "current_interval_usage_count": 90},
        ]}
        usage = minimax.parse_usage(payload)
        self.assertAlmostEqual(usage.weekly.pct, 90.0)
        self.assertIsNone(usage.five.pct)

    def test_missing_blocks_raise(self):
        with self.assertRaises(RuntimeError):
            minimax.parse_usage({"data": {"model_remains": []}})

    def test_remains_time_falls_back_when_end_time_is_absent(self):
        payload = {"model_remains": [
            {"start_time": 1792000000000, "remains_time": 600_000,
             "current_interval_total_count": 10, "current_interval_usage_count": 1},
        ]}
        usage = minimax.parse_usage(payload)
        self.assertIsNotNone(usage.five.reset_at)


class MiniMaxTransportTest(unittest.TestCase):
    def provider(self, **options) -> minimax.MiniMaxProvider:
        return minimax.MiniMaxProvider(
            ProviderConfig(name="minimax", options={"api_key": "k", **options})
        )

    def test_ping_joins_base_and_path(self):
        provider = self.provider()
        with mock.patch.object(minimax, "request_json", return_value={"usage": {"total_tokens": 4}}) as sent:
            result = provider.ping()
        self.assertTrue(result.ok)
        self.assertEqual(result.tokens, 4)
        self.assertEqual(sent.call_args.args[0], "https://api.minimax.io/v1/text/chatcompletion_v2")

    def test_custom_base_and_path(self):
        provider = self.provider(base_url="https://api.minimaxi.com/v1/", ping_path="chat/completions")
        with mock.patch.object(minimax, "request_json", return_value={}) as sent:
            provider.ping()
        self.assertEqual(sent.call_args.args[0], "https://api.minimaxi.com/v1/chat/completions")

    def test_ping_failure_is_returned_not_raised(self):
        provider = self.provider()
        with mock.patch.object(minimax, "request_json", side_effect=RuntimeError("network error")):
            result = provider.ping()
        self.assertFalse(result.ok)
        self.assertIn("network", result.error or "")


if __name__ == "__main__":
    unittest.main()
