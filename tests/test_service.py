import os
import tempfile
import unittest
from pathlib import Path

from windowping import service


class RenderUnitTest(unittest.TestCase):
    def test_from_checkout_sets_pythonpath(self):
        text = service.render_unit(python="/usr/bin/python3", root=Path("/tmp/repo"))
        self.assertIn("ExecStart=/usr/bin/python3 -m windowping watch", text)
        self.assertIn("Environment=PYTHONPATH=/tmp/repo", text)
        self.assertIn("WorkingDirectory=/tmp/repo", text)
        self.assertNotIn("@", text)

    def test_installed_package_omits_pythonpath(self):
        text = service.render_unit(python="/usr/bin/python3", root=None)
        self.assertIn("ExecStart=/usr/bin/python3 -m windowping watch", text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertNotIn("@", text)

    def test_template_has_no_leftover_tokens(self):
        self.assertTrue(service.TEMPLATE.is_file())
        self.assertNotIn("@EXECSTART@", service.render_unit(root=None))


class UnitPathTest(unittest.TestCase):
    def test_honours_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = tmp
            try:
                self.assertEqual(service.unit_path(), Path(tmp) / "systemd" / "user" / service.SERVICE)
            finally:
                if old is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = old


if __name__ == "__main__":
    unittest.main()
