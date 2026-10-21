"""systemd user-unit management: ``windowping service …``."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE = "windowping.service"
TEMPLATE = Path(__file__).resolve().parent / "templates" / "windowping.service"
_AUTO = object()  # sentinel: "detect the source root yourself"


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "systemd" / "user"


def unit_path() -> Path:
    return unit_dir() / SERVICE


def has_systemd() -> bool:
    return shutil.which("systemctl") is not None


def source_root() -> Path | None:
    """The checkout root when running from a source tree, else None."""
    root = Path(__file__).resolve().parent.parent
    return root if (root / "pyproject.toml").is_file() else None


def render_unit(python: str | None = None, root=_AUTO) -> str:
    python = python or sys.executable
    root = source_root() if root is _AUTO else root
    exec_start = f"{python} -m windowping watch"
    env_lines = ["Environment=PYTHONUNBUFFERED=1"]
    if root is not None:
        env_lines.insert(0, f"Environment=PYTHONPATH={root}")
    text = TEMPLATE.read_text(encoding="utf-8")
    return (
        text.replace("@EXECSTART@", exec_start)
        .replace("@ENVLINES@", "\n".join(env_lines))
        .replace("@WORKDIR@", str(root or Path.home()))
    )


def _systemctl(*args: str) -> int:
    if not has_systemd():
        print("windowping: systemctl not found (systemd user session required)", file=sys.stderr)
        return 2
    result = subprocess.run(["systemctl", "--user", *args])
    return result.returncode


def _journalctl(*args: str) -> int:
    if shutil.which("journalctl") is None:
        print("windowping: journalctl not found", file=sys.stderr)
        return 2
    return subprocess.run(["journalctl", "--user", "-u", SERVICE, *args]).returncode


def install(*, start: bool = True, force: bool = False) -> int:
    path = unit_path()
    if path.exists() and not force:
        current = path.read_text(encoding="utf-8")
        desired = render_unit()
        if current == desired:
            print(f"unit already up to date: {path}")
        else:
            print(f"unit exists, rewriting (use --force to silence): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_unit(), encoding="utf-8")
    path.chmod(0o644)
    print(f"wrote {path}")
    rc = _systemctl("daemon-reload")
    if rc:
        return rc
    rc = _systemctl("enable", SERVICE)
    if rc:
        return rc
    if start:
        rc = _systemctl("restart", SERVICE)
        if rc:
            return rc
        print(f"started {SERVICE}")
    else:
        print(f"enabled {SERVICE} (not started)")
    print(f"logs: journalctl --user -u {SERVICE} -f")
    return 0


def uninstall(*, stop: bool = True) -> int:
    if stop:
        _systemctl("disable", "--now", SERVICE)
    path = unit_path()
    if path.exists():
        path.unlink()
        print(f"removed {path}")
    else:
        print(f"no unit at {path}")
    _systemctl("daemon-reload")
    return 0


def status() -> int:
    path = unit_path()
    if not path.exists():
        print(f"unit not installed (expected {path})")
        print("install it with: windowping service install")
        return 1
    print(f"unit: {path}")
    return _systemctl("status", SERVICE, "--no-pager", "--lines", "10")


def logs(*, follow: bool = False, lines: int = 50) -> int:
    args = ["--no-pager", "-n", str(lines)]
    if follow:
        args.append("-f")
    return _journalctl(*args)


ACTIONS = ("install", "uninstall", "start", "stop", "restart", "enable", "disable", "status", "logs")


def run(action: str, *, start: bool = True, force: bool = False, follow: bool = False, lines: int = 50) -> int:
    if action == "install":
        return install(start=start, force=force)
    if action == "uninstall":
        return uninstall()
    if action == "status":
        return status()
    if action == "logs":
        return logs(follow=follow, lines=lines)
    mapping = {
        "start": ("start", SERVICE),
        "stop": ("stop", SERVICE),
        "restart": ("restart", SERVICE),
        "enable": ("enable", SERVICE),
        "disable": ("disable", SERVICE),
    }
    if action not in mapping:
        print(f"unknown service action: {action}", file=sys.stderr)
        return 2
    return _systemctl(*mapping[action])
