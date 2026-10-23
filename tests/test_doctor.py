import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from windowping import doctor
from windowping.config import Config, General, ProviderConfig, TelegramConfig
from windowping.providers.base import PingResult, Usage, Window


def make_config(tmp: str, **telegram) -> Config:
    base = Path(tmp)
    return Config(
        general=General(state_file=base / "state.json", history_file=base / "events.jsonl"),
        providers={"fake": ProviderConfig(name="fake")},
        telegram=TelegramConfig(**{"enabled": True, "bot_token": "t", "chat_id": 1, **telegram}),
        path=base / "config.toml",
    )


class FakeProvider:
    name = "fake"
    title = "Fake"

    def __init__(self, usage=None, error: Exception | None = None):
        self._usage = usage
        self._error = error

    def usage(self):
        if self._error:
            raise self._error
        return self._usage

    def ping(self):  # pragma: no cover - unused
        return PingResult(ok=True)


class ConfigCheckTest(unittest.TestCase):
    def test_missing_config_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            check = doctor.check_config(make_config(tmp))
            self.assertEqual(check.status, doctor.FAIL)

    def test_world_readable_secret_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            cfg.path.write_text('[telegram]\nbot_token = "secret"\n')
            os.chmod(cfg.path, 0o644)
            self.assertEqual(doctor.check_config(cfg).status, doctor.WARN)

    def test_owner_only_secret_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            cfg.path.write_text('[telegram]\nbot_token = "secret"\n')
            os.chmod(cfg.path, 0o600)
            self.assertEqual(doctor.check_config(cfg).status, doctor.OK)

    def test_paths_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = doctor.check_paths(make_config(tmp))
            self.assertEqual([c.status for c in checks], [doctor.OK, doctor.OK])


class ClockCheckTest(unittest.TestCase):
    def test_in_sync(self):
        now = 1_800_000_000.0
        self.assertEqual(doctor.check_clock(server_now=now - 0.5, now=now).status, doctor.OK)

    def test_small_skew_warns(self):
        now = 1_800_000_000.0
        self.assertEqual(doctor.check_clock(server_now=now - 300, now=now).status, doctor.WARN)

    def test_big_skew_fails(self):
        now = 1_800_000_000.0
        self.assertEqual(doctor.check_clock(server_now=now - 3600, now=now).status, doctor.FAIL)

    def test_no_network_skips(self):
        self.assertEqual(doctor.check_clock(server_now=None, now=1.0).status, doctor.SKIP)


class ProviderCheckTest(unittest.TestCase):
    def run_with(self, provider) -> list[doctor.Check]:
        original = doctor.build_providers
        doctor.build_providers = lambda config: [provider]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                return doctor.check_providers(make_config(tmp))
        finally:
            doctor.build_providers = original

    def test_healthy_provider(self):
        usage = Usage(provider="fake", five=Window(pct=42, reset_at=time.time() + 3600),
                      weekly=Window(pct=10), plan="plus")
        checks = self.run_with(FakeProvider(usage))
        self.assertEqual(checks[0].status, doctor.OK)
        self.assertIn("5h 42%", checks[0].detail)
        self.assertIn("plus", checks[0].detail)

    def test_rejected_token_points_at_credentials(self):
        checks = self.run_with(FakeProvider(error=RuntimeError("HTTP 401: unauthorized")))
        self.assertEqual(checks[0].status, doctor.FAIL)
        self.assertIn("credentials", checks[0].hint)

    def test_network_error_points_at_reachability(self):
        checks = self.run_with(FakeProvider(error=RuntimeError("network error: getaddrinfo failed")))
        self.assertEqual(checks[0].status, doctor.FAIL)
        self.assertIn("unreachable", checks[0].hint)

    def test_no_providers_warns(self):
        original = doctor.build_providers
        doctor.build_providers = lambda config: []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                checks = doctor.check_providers(make_config(tmp))
        finally:
            doctor.build_providers = original
        self.assertEqual(checks[0].status, doctor.WARN)


class BinaryCheckTest(unittest.TestCase):
    def test_api_mode_needs_no_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            cfg.providers["codex"] = ProviderConfig(name="codex", options={"ping_mode": "api"})
            checks = doctor.check_binaries(cfg, which=lambda name: None)
            self.assertTrue(all(c.status == doctor.OK for c in checks))

    def test_missing_cli_fails_for_cli_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            cfg.providers["codex"] = ProviderConfig(name="codex", options={"ping_mode": "cli"})
            checks = doctor.check_binaries(cfg, which=lambda name: None)
            self.assertEqual(checks[0].status, doctor.FAIL)
            self.assertIn("codex", checks[0].hint)

    def test_present_cli_is_reported_with_a_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            cfg.providers["codex"] = ProviderConfig(name="codex")
            checks = doctor.check_binaries(cfg, which=lambda name: f"/usr/bin/{name}")
            self.assertEqual(checks[0].detail, "/usr/bin/codex")


class TelegramCheckTest(unittest.TestCase):
    def test_disabled_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp, enabled=False)
            self.assertEqual(doctor.check_telegram(cfg)[0].status, doctor.SKIP)

    def test_bad_token_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = doctor.check_telegram(
                make_config(tmp), get_me=lambda: Exception("HTTP 401: Unauthorized")
            )
            self.assertEqual(checks[0].status, doctor.FAIL)

    def test_good_token_and_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = doctor.check_telegram(make_config(tmp), get_me=lambda: "my_bot")
            self.assertEqual(checks[0].status, doctor.OK)
            self.assertIn("@my_bot", checks[0].detail)
            self.assertEqual(checks[1].status, doctor.OK)

    def test_missing_chat_id_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            cfg.telegram.chat_id = None
            checks = doctor.check_telegram(cfg, get_me=lambda: "my_bot")
            self.assertEqual(checks[1].status, doctor.FAIL)

    def test_broken_digest_time_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = doctor.check_telegram(make_config(tmp, digest_at="25:99"), get_me=lambda: "b")
            digest = [c for c in checks if c.name == "digest"]
            self.assertEqual(digest[0].status, doctor.WARN)


class ServiceCheckTest(unittest.TestCase):
    def test_unit_missing_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = doctor.check_service(make_config(tmp), unit=Path(tmp) / "nope.service")
            self.assertEqual(checks[0].status, doctor.SKIP)

    def test_active_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp) / "windowping.service"
            unit.write_text("[Unit]\n")
            cfg = make_config(tmp)
            cfg.general.state_file.write_text(json.dumps({"updated_at": time.time()}))

            def fake(*args):
                return "active" if args[0] == "is-active" else "enabled"

            checks = doctor.check_service(cfg, systemctl=fake, unit=unit)
            self.assertEqual(checks[0].status, doctor.OK)
            self.assertEqual(checks[1].status, doctor.OK)

    def test_stopped_unit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp) / "windowping.service"
            unit.write_text("[Unit]\n")
            checks = doctor.check_service(
                make_config(tmp), systemctl=lambda *a: "inactive", unit=unit
            )
            self.assertEqual(checks[0].status, doctor.FAIL)

    def test_stale_watcher_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp) / "windowping.service"
            unit.write_text("[Unit]\n")
            cfg = make_config(tmp)
            cfg.general.state_file.write_text(json.dumps({"updated_at": time.time() - 7200}))
            checks = doctor.check_service(cfg, systemctl=lambda *a: "active", unit=unit)
            watcher = [c for c in checks if c.name == "watcher"][0]
            self.assertEqual(watcher.status, doctor.WARN)


class ReportTest(unittest.TestCase):
    def test_exit_code_follows_failures_not_warnings(self):
        report = doctor.Report().add(
            doctor.Check("a", doctor.OK, "fine"),
            doctor.Check("b", doctor.WARN, "meh"),
        )
        self.assertEqual(report.exit_code, 0)
        report.add(doctor.Check("c", doctor.FAIL, "broken", hint="fix it"))
        self.assertEqual(report.exit_code, 1)

    def test_text_is_aligned_and_shows_hints(self):
        report = doctor.Report().add(
            doctor.Check("provider commandcode", doctor.OK, "reachable"),
            doctor.Check("config", doctor.WARN, "world readable", hint="chmod 600"),
        )
        text = report.text(version="9.9.9")
        self.assertIn("9.9.9", text)
        self.assertIn("→ chmod 600", text)
        self.assertIn("1 ok", text)
        self.assertIn("1 warning(s)", text)

    def test_json_is_machine_readable(self):
        report = doctor.Report().add(doctor.Check("x", doctor.OK, "y"))
        payload = json.loads(report.json())
        self.assertEqual(payload["checks"][0]["name"], "x")
        self.assertEqual(payload["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
