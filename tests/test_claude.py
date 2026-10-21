import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from windowping.config import ProviderConfig
from windowping.http import HttpError
from windowping.providers import claude

USAGE_PAYLOAD = {
    "five_hour": {"utilization": 23.0, "resets_at": "2026-10-21T19:00:00.402137+00:00"},
    "seven_day": {"utilization": 41.0, "resets_at": "2026-10-25T08:00:00+00:00"},
    "seven_day_opus": {"utilization": 0.0, "resets_at": None},
    "limits": [
        {"kind": "session", "percent": 23, "resets_at": "2026-10-21T19:00:00+00:00"},
        {"kind": "weekly_all", "percent": 41, "resets_at": "2026-10-25T08:00:00+00:00"},
        {"kind": "weekly_scoped", "percent": 67, "resets_at": "2026-10-25T08:00:00+00:00",
         "scope": {"model": {"display_name": "Opus"}}},
        {"kind": "monthly_new_meter", "percent": 1, "resets_at": None, "scope": None},
    ],
}

FAKE_HELP = """\
Usage: claude [options] [command] [prompt]

Options:
  --model <model>                       Model for the current session
  --session-id <uuid>                   Use a specific session ID
  --settings <file-or-json>             Path to a settings JSON file
  --strict-mcp-config                   Only use MCP servers from --mcp-config
  --tools <tools...>                    Specify the list of available tools
"""


def provider(**options) -> claude.ClaudeProvider:
    options.setdefault("bin", "definitely-not-a-claude-binary")
    return claude.ClaudeProvider(ProviderConfig(name="claude", options=options))


class ParseUsageTest(unittest.TestCase):
    def test_windows(self):
        usage = claude.parse_usage(USAGE_PAYLOAD)
        self.assertEqual(usage.five.pct, 23.0)
        self.assertAlmostEqual(usage.five.reset_at, 1792609200.402137, places=3)
        self.assertFalse(usage.five.exceeded)
        self.assertEqual(usage.weekly.pct, 41.0)
        self.assertEqual(usage.weekly.reset_at, 1792915200.0)

    def test_scoped_limits_become_details(self):
        usage = claude.parse_usage(USAGE_PAYLOAD)
        self.assertEqual(usage.details, ["Opus weekly 67%", "monthly_new_meter 1%"])

    def test_legacy_bucket_keys(self):
        payload = {k: v for k, v in USAGE_PAYLOAD.items() if k != "limits"}
        payload["seven_day_sonnet"] = None
        usage = claude.parse_usage(payload)
        self.assertEqual(usage.details, ["opus weekly 0%"])

    def test_window_not_started(self):
        usage = claude.parse_usage({"five_hour": {"utilization": 0, "resets_at": None},
                                    "seven_day": {"utilization": 5, "resets_at": None}})
        self.assertTrue(usage.five.enforced)
        self.assertFalse(usage.five.active)
        self.assertEqual(usage.five.pct, 0)

    def test_missing_window_is_not_enforced(self):
        usage = claude.parse_usage({"five_hour": None})
        self.assertFalse(usage.five.enforced)
        self.assertFalse(usage.weekly.enforced)

    def test_exhausted(self):
        usage = claude.parse_usage({"seven_day": {"utilization": 100,
                                                  "resets_at": "2026-10-25T08:00:00Z"}})
        self.assertTrue(usage.weekly.exceeded)
        self.assertEqual(usage.weekly.reset_at, 1792915200.0)


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth = Path(self.tmp.name) / ".credentials.json"
        self.auth.write_text(json.dumps({
            "claudeAiOauth": {"accessToken": "old", "refreshToken": "r1",
                              "expiresAt": 1, "subscriptionType": "max"},
            "mcpOAuth": {"some-server": {"accessToken": "keep-me"}},
        }), encoding="utf-8")

    def test_reads_wrapped_and_flat_credentials(self):
        self.assertEqual(provider(auth_file=str(self.auth)).token(), "old")
        self.auth.write_text(json.dumps({"accessToken": "flat"}), encoding="utf-8")
        self.assertEqual(provider(auth_file=str(self.auth)).token(), "flat")

    def test_missing_credentials_say_how_to_fix(self):
        with self.assertRaisesRegex(RuntimeError, "log in"):
            provider(auth_file=str(Path(self.tmp.name) / "nope.json")).token()

    def test_401_reloads_then_refreshes_and_writes_back(self):
        calls = []

        def fake_request(url, *, method="GET", headers=None, body=None, timeout=20.0):
            calls.append((method, url, (headers or {}).get("Authorization"), body))
            if url == claude.OAUTH_TOKEN_URL:
                return {"access_token": "new", "refresh_token": "r2", "expires_in": 28800}
            if headers["Authorization"] == "Bearer old":
                raise HttpError(401, "token expired", url)
            return USAGE_PAYLOAD

        p = provider(auth_file=str(self.auth))
        with mock.patch.object(claude, "request_json", fake_request):
            usage = p.usage()
        self.assertEqual(usage.five.pct, 23.0)
        self.assertEqual(usage.plan, "max")
        # old token -> (reload: still old, no retry) -> refresh -> new token
        self.assertEqual([c[2] for c in calls], ["Bearer old", None, "Bearer new"])
        self.assertEqual(calls[1][3]["client_id"], claude.OAUTH_CLIENT_ID)
        self.assertEqual(calls[1][3]["refresh_token"], "r1")

        stored = json.loads(self.auth.read_text(encoding="utf-8"))
        self.assertEqual(stored["claudeAiOauth"]["accessToken"], "new")
        self.assertEqual(stored["claudeAiOauth"]["refreshToken"], "r2")
        self.assertEqual(stored["claudeAiOauth"]["subscriptionType"], "max")
        self.assertGreater(stored["claudeAiOauth"]["expiresAt"], time.time() * 1000)
        self.assertEqual(stored["mcpOAuth"], {"some-server": {"accessToken": "keep-me"}})

    def test_401_uses_a_token_the_cli_refreshed_meanwhile(self):
        p = provider(auth_file=str(self.auth))
        p.token()  # cache "old"
        self.auth.write_text(json.dumps({"claudeAiOauth": {"accessToken": "cli-fresh"}}),
                             encoding="utf-8")
        seen = []

        def fake_request(url, *, method="GET", headers=None, body=None, timeout=20.0):
            seen.append(headers["Authorization"])
            if headers["Authorization"] == "Bearer old":
                raise HttpError(401, "token expired", url)
            return USAGE_PAYLOAD

        with mock.patch.object(claude, "request_json", fake_request):
            p.usage()
        self.assertEqual(seen, ["Bearer old", "Bearer cli-fresh"])

    def test_usage_headers(self):
        seen = {}

        def fake_request(url, *, method="GET", headers=None, body=None, timeout=20.0):
            seen.update(headers)
            seen["url"] = url
            return USAGE_PAYLOAD

        with mock.patch.object(claude, "request_json", fake_request):
            provider(auth_file=str(self.auth)).usage()
        self.assertEqual(seen["url"], claude.USAGE_URL)
        self.assertEqual(seen["anthropic-beta"], claude.OAUTH_BETA)
        self.assertEqual(seen["User-Agent"], f"claude-code/{claude.FALLBACK_VERSION}")


class UsageCacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.auth = Path(tmp.name) / ".credentials.json"
        self.auth.write_text(json.dumps({"claudeAiOauth": {"accessToken": "t"}}), encoding="utf-8")
        self.calls = 0
        self.payload = {"five_hour": {"utilization": 10, "resets_at": "2099-01-01T00:00:00Z"},
                        "seven_day": {"utilization": 10, "resets_at": "2099-01-01T00:00:00Z"}}
        self.error = None

        def fake_request(url, **kwargs):
            self.calls += 1
            if self.error:
                raise self.error
            return self.payload

        patcher = mock.patch.object(claude, "request_json", fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_are_reused_within_the_interval(self):
        p = provider(auth_file=str(self.auth))
        p.usage()
        p.usage()
        self.assertEqual(self.calls, 1)

    def test_passed_reset_forces_a_fresh_read(self):
        self.payload["five_hour"]["resets_at"] = "2000-01-01T00:00:00Z"
        p = provider(auth_file=str(self.auth))
        p.usage()
        p.usage()
        self.assertEqual(self.calls, 2)

    def test_ping_invalidates_the_cache(self):
        p = provider(auth_file=str(self.auth))
        p.usage()
        p.ping()  # fails fast: the binary does not exist
        p.usage()
        self.assertEqual(self.calls, 2)

    def test_throttle_falls_back_to_the_cached_read(self):
        p = provider(auth_file=str(self.auth), read_interval=0)
        first = p.usage()
        self.error = HttpError(429, "rate limited")
        self.assertIs(p.usage(), first)

    def test_throttle_without_cache_is_an_error(self):
        self.error = HttpError(429, "rate limited")
        with self.assertRaises(HttpError):
            provider(auth_file=str(self.auth)).usage()


class PingCommandTest(unittest.TestCase):
    def test_isolation_flags_follow_the_installed_cli(self):
        p = provider(model="haiku", prompt="ok")
        p._help = FAKE_HELP
        command = p.ping_command("11111111-2222-4333-8444-555555555555")
        self.assertEqual(command[:3], ["definitely-not-a-claude-binary", "--model", "haiku"])
        self.assertIn("--session-id", command)
        self.assertEqual(command[command.index("--settings") + 1], claude.PING_SETTINGS)
        self.assertIn("--strict-mcp-config", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[-2:], ["--", "ok"])
        self.assertNotIn("-p", command)

    def test_old_cli_gets_no_unknown_flags(self):
        p = provider()
        p._help = "Options:\n  --model <model>  Model\n"
        self.assertEqual(p.ping_command("x"), ["definitely-not-a-claude-binary", "--model", "haiku", "--", "ok"])

    def test_flag_mentioned_in_a_description_does_not_count(self):
        help_text = "  --bare        Minimal mode. Explicitly provide\n                --settings, --agents\n"
        self.assertTrue(claude.flag_supported(help_text, "--bare"))
        self.assertFalse(claude.flag_supported(help_text, "--settings"))

    def test_print_only_extra_args_are_dropped(self):
        extra = ["-p", "--output-format", "json", "--max-turns=1", "--effort", "low", "--bare"]
        self.assertEqual(claude.interactive_args(extra), ["--effort", "low"])

    def test_user_flags_win_over_isolation(self):
        p = provider(extra_args=["--tools", "Read"])
        p._help = FAKE_HELP
        command = p.ping_command("11111111-2222-4333-8444-555555555555")
        self.assertEqual(command.count("--tools"), 1)
        self.assertEqual(command[command.index("--tools") + 1], "Read")


class PingDirTest(unittest.TestCase):
    def test_trusted_workdir_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(claude.pick_ping_dir(Path(tmp), {tmp}, True), Path(tmp))

    def test_untrusted_workdir_borrows_a_clean_trusted_folder(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as a, \
                tempfile.TemporaryDirectory() as b:
            (Path(a) / ".claude").mkdir()
            (Path(a) / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            trusted = {a, b, "relative/dir", str(Path(home) / "gone")}
            self.assertEqual(claude.pick_ping_dir(Path(home), trusted, True), Path(b))
            self.assertEqual(claude.pick_ping_dir(Path(home), trusted, False), Path(home))

    def test_trusted_dirs_reads_claude_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".claude.json"
            path.write_text(json.dumps({"projects": {
                "/a": {"hasTrustDialogAccepted": True},
                "/b": {"hasTrustDialogAccepted": False},
                "/c": {},
            }}), encoding="utf-8")
            self.assertEqual(claude.trusted_dirs(path), {"/a"})
            self.assertEqual(claude.trusted_dirs(Path(tmp) / "missing.json"), set())


class TranscriptTest(unittest.TestCase):
    SID = "11111111-2222-4333-8444-555555555555"

    def write(self, root: Path, *entries) -> Path:
        folder = root / "projects" / "-home-me-repo"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.SID}.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        (folder / self.SID).mkdir()
        return path

    def test_real_reply_is_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(Path(tmp), {"type": "user", "message": {"content": "ok"}}, {
                "type": "assistant", "requestId": "req_1",
                "message": {"model": "claude-haiku-5-5", "content": [{"type": "text", "text": "OK"}],
                            "usage": {"input_tokens": 3, "cache_creation_input_tokens": 100,
                                      "cache_read_input_tokens": 9000, "output_tokens": 2}},
            })
            found = claude.read_transcript(Path(tmp), self.SID)
            self.assertTrue(found.answered)
            self.assertEqual(found.model, "claude-haiku-5-5")
            self.assertEqual(found.tokens, 9105)

    def test_synthetic_error_is_not_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(Path(tmp), {
                "type": "assistant", "isApiErrorMessage": True,
                "message": {"model": "<synthetic>", "content": [
                    {"type": "text", "text": "Failed to authenticate: OAuth session expired"}]},
            })
            found = claude.read_transcript(Path(tmp), self.SID)
            self.assertFalse(found.answered)
            self.assertIn("OAuth session expired", found.error)

    def test_remove_deletes_only_this_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(Path(tmp), {"type": "user"})
            other = path.with_name("99999999-2222-4333-8444-555555555555.jsonl")
            other.write_text("{}", encoding="utf-8")
            claude.remove_transcript(Path(tmp), "*")  # not a UUID: refused
            self.assertTrue(path.exists())
            claude.remove_transcript(Path(tmp), self.SID)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix("").exists())
            self.assertTrue(other.exists())


class OutputMatchingTest(unittest.TestCase):
    def test_denial_survives_ansi_and_wrapping(self):
        text = ("\x1b[31mYour organization has disabled Claude\x1b[0m\r\n│ subscription access "
                "for Claude Code\x1b[K")
        self.assertTrue(claude.access_denied(text))
        self.assertFalse(claude.access_denied("all good"))

    def test_trust_prompt(self):
        self.assertTrue(claude.trust_prompt("\x1b[1m❯ 1. Yes, I trust this folder\x1b[0m"))
        self.assertFalse(claude.trust_prompt("OK"))


FAKE_CLAUDE = textwrap.dedent('''\
    import json, os, sys
    from pathlib import Path
    args = sys.argv[1:]
    if args == ["--help"]:
        print({help!r})
        raise SystemExit(0)
    if args == ["--version"]:
        print("9.9.9 (Claude Code)")
        raise SystemExit(0)
    mode = os.environ["FAKE_CLAUDE_MODE"]
    Path(os.environ["FAKE_CLAUDE_ARGV"]).write_text(json.dumps(
        {{"argv": args, "cwd": os.getcwd(), "isatty": sys.stdin.isatty(),
         "no_mds": os.environ.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS")}}))
    if mode == "trust":
        print("Do you trust the files in this folder?  1. Yes, I trust this folder  2. No, exit")
        sys.stdin.readline()
        raise SystemExit(0)
    if mode == "denied":
        print("Your organization has disabled Claude subscription access for Claude Code")
        sys.stdin.readline()
        raise SystemExit(0)
    print("\\x1b[2J> " + args[-1], flush=True)
    sys.stdin.readline()  # Enter submits the prompt
    if mode == "ok":
        sid = args[args.index("--session-id") + 1]
        folder = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "-fake"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (sid + ".jsonl")).write_text(json.dumps({{
            "type": "assistant", "requestId": "req_1",
            "message": {{"model": "claude-haiku-fake", "content": [{{"type": "text", "text": "OK"}}],
                        "usage": {{"input_tokens": 10, "output_tokens": 2}}}}}}) + "\\n")
    print("OK", flush=True)
    while sys.stdin.readline().strip() != "/exit":
        pass
''').format(help=FAKE_HELP)


@unittest.skipUnless(hasattr(os, "openpty"), "the interactive ping needs a POSIX pty")
class InteractivePingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        script = self.root / "claude"
        script.write_text(f"#!{sys.executable}\n" + FAKE_CLAUDE, encoding="utf-8")
        script.chmod(0o755)
        self.argv_file = self.root / "argv.json"
        self.config = self.root / "config"
        self.config.mkdir()
        self.workdir = self.root / "work"
        self.workdir.mkdir()
        env = mock.patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.config),
            "FAKE_CLAUDE_ARGV": str(self.argv_file),
        })
        env.start()
        self.addCleanup(env.stop)
        self.provider = claude.ClaudeProvider(
            ProviderConfig(name="claude", options={"bin": str(script)}),
            workdir=self.workdir,
            ping_timeout=30,
        )
        self.provider.timings = claude.Timings(
            startup_timeout=5, startup_settle=0.3, turn_min=0.3, turn_quiet=0.4,
            turn_max=5, exit_grace=3, poll=0.05,
        )

    def ping(self, mode: str):
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_MODE": mode}):
            result = self.provider.ping()
        return result, json.loads(self.argv_file.read_text(encoding="utf-8"))

    def test_successful_ping_is_proven_and_cleaned_up(self):
        result, seen = self.ping("ok")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.model, "claude-haiku-fake")
        self.assertEqual(result.tokens, 12)
        self.assertTrue(seen["isatty"])
        self.assertEqual(seen["no_mds"], "1")
        self.assertEqual(seen["argv"][-2:], ["--", "ok"])
        self.assertIn("--session-id", seen["argv"])
        self.assertEqual(Path(seen["cwd"]).resolve(), self.workdir.resolve())
        self.assertEqual(list(self.config.glob("projects/*/*.jsonl")), [])

    def test_no_reply_is_a_failure(self):
        result, _ = self.ping("silent")
        self.assertFalse(result.ok)
        self.assertIn("no request reached Claude", result.error)

    def test_trust_dialog_is_reported(self):
        result, _ = self.ping("trust")
        self.assertFalse(result.ok)
        self.assertIn("trust", result.error)

    def test_subscription_denial_is_reported(self):
        result, _ = self.ping("denied")
        self.assertFalse(result.ok)
        self.assertIn("subscription access is unavailable", result.error)


if __name__ == "__main__":
    unittest.main()
