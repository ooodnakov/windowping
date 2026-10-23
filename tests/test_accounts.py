import tempfile
import unittest
from pathlib import Path

from windowping.bot import BotCommands
from windowping.config import load
from windowping.providers import build_matching, build_one, build_providers, instances, split_instance


CONFIG = '''
[general]
state_file = "{tmp}/state.json"

[providers.codex]
enabled = true
ping_mode = "api"
auth_file = "{tmp}/main-auth.json"

[providers.codex.accounts.personal]
auth_file = "{tmp}/personal-auth.json"

[providers.codex.accounts.work]
auth_file = "{tmp}/work-auth.json"
ping_mode = "cli"

[providers.codex.accounts.old]
enabled = false
auth_file = "{tmp}/old-auth.json"

[providers.glm]
enabled = false
'''


class InstanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "config.toml"
        path.write_text(CONFIG.format(tmp=self.tmp.name))
        self.config = load(path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_split_instance(self):
        self.assertEqual(split_instance("codex:work"), ("codex", "work"))
        self.assertEqual(split_instance("codex"), ("codex", None))

    def test_one_instance_per_account_minus_disabled(self):
        names = [p.name for p in build_providers(self.config)]
        self.assertEqual(names, ["codex:personal", "codex:work"])

    def test_titles_carry_the_account_label(self):
        titles = {p.name: p.title for p in build_providers(self.config)}
        self.assertEqual(titles["codex:work"], "Codex (work)")
        self.assertEqual(titles["codex:personal"], "Codex (personal)")

    def test_account_keys_override_provider_keys(self):
        work = build_one(self.config, "codex:work")
        assert work is not None
        self.assertEqual(getattr(work, "cfg").get("ping_mode"), "cli")
        self.assertEqual(
            str(getattr(work, "cfg").path("auth_file", Path("/nonexistent"))),
            f"{self.tmp.name}/work-auth.json",
        )
        # untouched keys still come from the provider section
        personal = build_one(self.config, "codex:personal")
        assert personal is not None
        self.assertEqual(getattr(personal, "cfg").get("ping_mode"), "api")

    def test_disabled_account_is_skipped(self):
        self.assertIsNone(build_one(self.config, "codex:old"))

    def test_base_name_selects_every_account(self):
        self.assertEqual([p.name for p in build_matching(self.config, "codex")], ["codex:personal", "codex:work"])

    def test_exact_name_selects_one(self):
        self.assertEqual([p.name for p in build_matching(self.config, "codex:work")], ["codex:work"])

    def test_disabled_provider_builds_nothing(self):
        self.assertEqual(build_matching(self.config, "glm"), [])

    def test_unknown_name_is_empty(self):
        self.assertEqual(build_matching(self.config, "nope"), [])

    def test_provider_without_accounts_is_a_single_instance(self):
        path = Path(self.tmp.name) / "plain.toml"
        path.write_text('[general]\nstate_file = "' + self.tmp.name + '/state.json"\n[providers.glm]\nenabled = true\napi_key = "k"\n')
        plain = load(path)
        self.assertEqual([p.name for p in build_providers(plain)], ["glm"])
        self.assertEqual(instances("glm", plain.providers["glm"])[0][0], "glm")

    def test_bot_resolves_a_base_name_to_all_accounts(self):
        commands = BotCommands(self.config)
        providers, error = commands._resolve("codex", "en")
        self.assertIsNone(error)
        self.assertEqual([p.name for p in providers], ["codex:personal", "codex:work"])

    def test_bot_resolves_one_account(self):
        commands = BotCommands(self.config)
        providers, error = commands._resolve("codex:work", "en")
        self.assertIsNone(error)
        self.assertEqual([p.name for p in providers], ["codex:work"])

    def test_bot_still_rejects_an_unknown_provider(self):
        commands = BotCommands(self.config)
        providers, error = commands._resolve("nope", "en")
        self.assertEqual(providers, [])
        self.assertIn("nope", error or "")


if __name__ == "__main__":
    unittest.main()
