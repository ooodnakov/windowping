import json
import tempfile
import unittest
from pathlib import Path

from windowping.providers import codex, commandcode, glm

GLM_PAYLOAD = {
    "code": 200,
    "success": True,
    "data": {
        "level": "lite",
        "limits": [
            # deliberately out of order: identity must come from unit, not index
            {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "usage": 10000,
             "currentValue": 2500, "remaining": 7500, "percentage": 25,
             "nextResetTime": 1792590322983},
            {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 2000,
             "currentValue": 200, "remaining": 1800, "percentage": 10,
             "nextResetTime": 1792584122983},
        ],
    },
}

CC_PAYLOAD = {
    "credits": {"monthlyCredits": 46.65, "purchasedCredits": 0, "freeCredits": 0},
    "windowLimits": {
        "limited": True,
        "fiveHour": {"used": 0.05, "cap": 14, "exceeded": False, "resetAt": 1792601739207},
        "weekly": {"used": 7.27, "cap": 35, "exceeded": False, "resetAt": 1793032943320},
    },
}


class GLMTest(unittest.TestCase):
    def test_parse_maps_windows_by_unit(self):
        usage = glm.parse_usage(GLM_PAYLOAD)
        self.assertEqual(usage.plan, "lite")
        assert usage.five.pct is not None and usage.weekly.pct is not None
        self.assertAlmostEqual(usage.five.pct, 10)
        self.assertEqual(usage.five.reset_at, 1792584122.983)
        self.assertFalse(usage.five.exceeded)
        self.assertAlmostEqual(usage.weekly.pct, 25)
        self.assertEqual(usage.weekly.reset_at, 1792590322.983)

    def test_percentage_falls_back_to_counts(self):
        payload = {"data": {"limits": [{"type": "TOKENS_LIMIT", "unit": 3,
                                        "usage": 2000, "currentValue": 500}]}}
        usage = glm.parse_usage(payload)
        assert usage.five.pct is not None
        self.assertAlmostEqual(usage.five.pct, 25)
        self.assertIsNone(usage.five.reset_at)

    def test_exhausted_weekly(self):
        payload = {"data": {"limits": [{"type": "CREDIT_LIMIT", "unit": 6,
                                        "usage": 10000, "currentValue": 10011,
                                        "percentage": 100, "nextResetTime": 1792590322983}]}}
        usage = glm.parse_usage(payload)
        self.assertTrue(usage.weekly.exceeded)


class CommandCodeTest(unittest.TestCase):
    def test_parse_windows(self):
        usage = commandcode.parse_windows(CC_PAYLOAD)
        assert usage.five.pct is not None and usage.weekly.pct is not None
        self.assertAlmostEqual(usage.five.pct, 0.05 / 14 * 100)
        self.assertEqual(usage.five.reset_at, 1792601739.207)
        self.assertAlmostEqual(usage.weekly.pct, 7.27 / 35 * 100)
        self.assertIn("$46.65 monthly credits left", usage.details)

    def test_missing_windows_are_not_enforced(self):
        usage = commandcode.parse_windows({"windowLimits": {"limited": False}})
        self.assertFalse(usage.five.enforced)
        self.assertFalse(usage.weekly.enforced)


class CodexTest(unittest.TestCase):
    def test_windows_classified_by_length(self):
        payload = {
            "plan_type": "plus",
            "rate_limit": {
                "primary_window": {"used_percent": 63, "limit_window_seconds": 18000,
                                   "reset_at": 1792601525},
                "secondary_window": {"used_percent": 29, "limit_window_seconds": 604800,
                                     "reset_at": 1793135230},
            },
            "rate_limit_reset_credits": {"available_count": 3},
        }
        usage = codex.parse_usage(payload, now=1792580000)
        self.assertEqual(usage.plan, "plus")
        assert usage.five.pct is not None
        self.assertEqual(usage.five.pct, 63)
        self.assertEqual(usage.five.reset_at, 1792601525)
        self.assertEqual(usage.weekly.pct, 29)
        self.assertIn("3 reset credit(s) available", usage.details)

    def test_weekly_only_plan(self):
        # OpenAI has removed the 5h window before: the weekly one becomes primary
        payload = {"rate_limit": {"primary_window": {"used_percent": 40,
                                                     "limit_window_seconds": 604800,
                                                     "reset_at": 1793135230}}}
        usage = codex.parse_usage(payload, now=1792580000)
        self.assertFalse(usage.five.enforced)
        assert usage.weekly.pct is not None
        self.assertEqual(usage.weekly.pct, 40)

    def test_reset_after_seconds_is_converted(self):
        payload = {"rate_limit": {"primary_window": {"used_percent": 1,
                                                     "limit_window_seconds": 18000,
                                                     "reset_after_seconds": 600}}}
        usage = codex.parse_usage(payload, now=1000)
        self.assertEqual(usage.five.reset_at, 1600)

    def test_cheapest_model_prefers_budget_tier(self):
        cache = {
            "models": [
                {"slug": "gpt-flagship", "description": "Latest workhorse", "priority": 1},
                {"slug": "gpt-mini", "description": "Fast and affordable", "priority": 9},
                {"slug": "gpt-luna", "description": "Cheap and fast", "priority": 5},
                {"slug": "internal", "description": "cheap", "visibility": "hide"},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models_cache.json"
            path.write_text(json.dumps(cache), encoding="utf-8")
            self.assertEqual(codex.cheapest_model(path), "gpt-mini")

    def test_cheapest_model_missing_cache(self):
        self.assertEqual(codex.cheapest_model(Path("/nonexistent/models_cache.json")), "")

    def test_ping_command_flags(self):
        from windowping.config import ProviderConfig

        cfg = ProviderConfig(name="codex", options={"model": "gpt-x", "effort": "low"})
        provider = codex.CodexProvider(cfg)
        command = provider.ping_command()
        self.assertEqual(command[0], "codex")
        self.assertIn("--ephemeral", command)
        self.assertIn("read-only", command)
        self.assertIn("gpt-x", command)
        self.assertEqual(command[-1], "ok")


if __name__ == "__main__":
    unittest.main()
