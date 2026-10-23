"""``windowping doctor``: find the failures that would otherwise be silent.

Everything here is read-only. The point is to answer "why is nothing happening"
without reading code: an expired token, a missing CLI, a skewed clock, a unit
that is installed but stopped, a watcher that has not ticked in ten minutes.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import __version__, service
from .config import Config
from .history import History, default_path
from .providers import build_providers
from .quiet import describe as describe_quiet
from .render import fmt_delta

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"

MARKS = {OK: "✓", WARN: "!", FAIL: "✗", SKIP: "·"}
CLOCK_URL = "https://api.telegram.org/"
_UNSET = object()  # "go fetch it"; a plain None means "no time source available"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""

    def line(self, width: int = 18) -> str:
        head = f"{MARKS.get(self.status, '?')} {self.name:<{width}}{self.detail}"
        pad = " " * (width + 2)
        return head + (f"\n{pad}→ {self.hint}" if self.hint else "")


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, *checks: Check) -> "Report":
        self.checks.extend(checks)
        return self

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == WARN]

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0

    def summary(self) -> str:
        ok = sum(1 for c in self.checks if c.status == OK)
        bits = [f"{ok} ok"]
        if self.warnings:
            bits.append(f"{len(self.warnings)} warning(s)")
        if self.failures:
            bits.append(f"{len(self.failures)} failed")
        return ", ".join(bits)

    def text(self, *, version: str = __version__) -> str:
        lines = [f"windowping doctor — {version}", ""]
        width = max((len(check.name) for check in self.checks), default=18) + 2
        lines.extend(check.line(width) for check in self.checks)
        lines.extend(["", self.summary()])
        return "\n".join(lines)

    def json(self) -> str:
        return json.dumps(
            {
                "version": __version__,
                "summary": self.summary(),
                "exit_code": self.exit_code,
                "checks": [asdict(check) for check in self.checks],
            },
            indent=2,
        )


# -- individual checks --------------------------------------------------- #


def check_python() -> Check:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info < (3, 11):
        return Check("python", FAIL, version, "windowping needs Python 3.11 or newer")
    return Check("python", OK, version)


def _mode(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


def check_config(config: Config) -> Check:
    path = Path(config.path)
    if not path.exists():
        return Check("config", FAIL, f"missing: {path}", "run: windowping config init")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Check("config", FAIL, f"unreadable: {exc}", "check the file permissions")
    mode = stat.S_IMODE(path.stat().st_mode)
    has_secret = any(
        line.split("=", 1)[0].strip() in {"bot_token", "api_key", "token", "access_token"}
        and line.split("=", 1)[1].strip().strip('"')
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    if has_secret and mode & 0o077:
        return Check(
            "config",
            WARN,
            f"{path} (mode {oct(mode)})",
            "secrets are readable by other users: chmod 600 " + str(path),
        )
    return Check("config", OK, f"{path} (mode {oct(mode)})")


def check_paths(config: Config) -> list[Check]:
    checks: list[Check] = []
    state_dir = Path(config.general.state_file).parent
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(Check("state dir", OK, str(state_dir)))
    except OSError as exc:
        checks.append(Check("state dir", FAIL, f"{state_dir}: {exc}", "make it writable for this user"))
    history = config.general.history_file or default_path(config.general.state_file)
    if Path(history).exists():
        size = Path(history).stat().st_size
        events = len(History(history).events(since=time.time() - 7 * 86400))
        checks.append(Check("event log", OK, f"{history} ({size} B, {events} event(s) in 7d)"))
    else:
        checks.append(Check("event log", OK, f"{history} (will be created)"))
    return checks


def http_date(url: str = CLOCK_URL, timeout: float = 10.0) -> float | None:
    """Server time from any HTTP response, including a 404."""
    request = urllib.request.Request(url, method="GET")
    request.add_header("User-Agent", f"windowping/{__version__}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.headers.get("Date")
    except urllib.error.HTTPError as exc:
        raw = exc.headers.get("Date") if exc.headers else None
    except (urllib.error.URLError, OSError):
        return None
    if not raw:
        return None
    parsed = email.utils.parsedate_to_datetime(raw)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def check_clock(server_now: float | None | object = _UNSET, now: float | None = None) -> Check:
    now = time.time() if now is None else now
    server_now = http_date() if server_now is _UNSET else server_now
    if server_now is None:
        return Check("clock", SKIP, "could not reach a time source", "no network is not fatal")
    skew = now - server_now
    detail = f"{skew:+.1f}s vs Telegram"
    if abs(skew) > 600:
        return Check(
            "clock",
            FAIL,
            detail,
            "the host clock is badly off; window resets and pings will be misjudged",
        )
    if abs(skew) > 120:
        return Check("clock", WARN, detail, "check NTP: timedatectl status")
    return Check("clock", OK, detail)


def check_providers(config: Config, *, timeout: float | None = None) -> list[Check]:
    checks: list[Check] = []
    providers = build_providers(config)
    if not providers:
        return [Check("providers", WARN, "none enabled", "enable at least one [providers.*] section")]
    for provider in providers:
        try:
            usage = provider.usage()
        except Exception as exc:  # noqa: BLE001 - that is the whole point
            text = str(exc)
            hint = ""
            lowered = text.lower()
            if "401" in lowered or "403" in lowered or "unauthor" in lowered or "invalid api key" in lowered:
                hint = "credentials were rejected: log in again or replace the key"
            elif "network" in lowered or "timed out" in lowered or "getaddrinfo" in lowered:
                hint = "the endpoint is unreachable: check DNS, proxy or VPN"
            elif "no " in lowered and ("key" in lowered or "token" in lowered):
                hint = "no credentials found for this provider"
            checks.append(Check(f"provider {provider.name}", FAIL, text[:120], hint))
            continue
        bits = []
        if usage.five.pct is not None:
            bits.append(f"5h {usage.five.pct:.0f}%")
        if usage.five.reset_at:
            bits.append(f"resets in {fmt_delta(max(0.0, usage.five.reset_at - time.time()))}")
        if usage.weekly.pct is not None:
            bits.append(f"weekly {usage.weekly.pct:.0f}%")
        if usage.plan:
            bits.append(usage.plan)
        checks.append(Check(f"provider {provider.name}", OK, " · ".join(bits) or "reachable"))
    return checks


def check_binaries(config: Config, *, which=shutil.which) -> list[Check]:
    checks: list[Check] = []
    rules = (
        ("codex", "codex", "the codex CLI is missing; it is only needed for ping_mode = \"cli\""),
        ("claude", "claude", "the claude CLI is missing; it is only needed for ping_mode = \"cli\""),
    )
    for provider_name, binary, hint in rules:
        section = config.providers.get(provider_name)
        if section is None or not section.enabled:
            continue
        if not uses_cli_ping(section):
            checks.append(Check(f"{provider_name} cli", OK, "not needed (ping_mode = api)"))
            continue
        path = which(binary)
        if path:
            checks.append(Check(f"{provider_name} cli", OK, path))
        else:
            checks.append(Check(f"{provider_name} cli", FAIL, f"{binary!r} not in PATH", hint))
    return checks


def uses_cli_ping(section) -> bool:
    mode = str(section.get("ping_mode", "cli") or "cli").strip().lower()
    return mode != "api"


def check_telegram(config: Config, *, get_me=None) -> list[Check]:
    tg = config.telegram
    if not tg.enabled:
        return [Check("telegram", SKIP, "disabled", "set [telegram] enabled = true to get messages")]
    checks: list[Check] = []
    token = tg.resolve_token()
    if not token:
        return [Check("telegram", FAIL, "no bot token", "set bot_token or the env var named in bot_token_env")]
    me = get_me() if get_me else _get_me(token)
    if isinstance(me, Exception) or me is None:
        checks.append(Check("telegram", FAIL, f"token rejected: {me}", "check the token with @BotFather"))
    else:
        checks.append(Check("telegram", OK, f"@{me}"))
    if tg.chat_id is None:
        checks.append(Check("telegram chat", FAIL, "chat_id is not set", "set [telegram] chat_id"))
    else:
        checks.append(Check("telegram chat", OK, f"chat_id {tg.chat_id}"))
    quiet = describe_quiet(tg.quiet_hours)
    checks.append(
        Check(
            "quiet hours",
            OK,
            f"{quiet} (silent deliveries)" if quiet != "off" else "off",
        )
    )
    if tg.digest_at:
        try:
            hour, minute = (int(part) for part in tg.digest_at.split(":", 1))
            valid = 0 <= hour <= 23 and 0 <= minute <= 59
        except ValueError:
            valid = False
        if not valid:
            checks.append(Check("digest", WARN, f"bad digest_at={tg.digest_at!r}", "expected HH:MM, or empty to disable"))
        else:
            checks.append(Check("digest", OK, f"daily after {tg.digest_at}"))
    return checks


def _get_me(token: str) -> str | Exception:
    url = f"https://api.telegram.org/bot{token}/getMe"
    request = urllib.request.Request(url, method="GET")
    request.add_header("User-Agent", f"windowping/{__version__}")
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:120]
        return Exception(f"HTTP {exc.code}: {detail}")
    except (urllib.error.URLError, OSError) as exc:
        return Exception(str(exc))
    if not isinstance(payload, dict) or not payload.get("ok"):
        return Exception(str(payload)[:120])
    return str((payload.get("result") or {}).get("username") or "ok")


def _systemctl(*args: str) -> str | None:
    if shutil.which("systemctl") is None:
        return None
    try:
        result = subprocess.run(
            ["systemctl", "--user", *args], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def check_service(config: Config, *, systemctl=None, unit: Path | None = None) -> list[Check]:
    checks: list[Check] = []
    unit = unit or service.unit_path()
    if not Path(unit).exists():
        checks.append(Check("service", SKIP, "unit not installed", "install it: windowping service install"))
    else:
        call = systemctl or _systemctl
        active = call("is-active", service.SERVICE)
        enabled = call("is-enabled", service.SERVICE)
        if call is None or active is None:
            checks.append(Check("service", SKIP, "systemctl unavailable"))
        elif active == "active":
            checks.append(Check("service", OK, f"active, {enabled or 'unknown'}"))
        else:
            checks.append(Check("service", FAIL, f"{active or 'unknown'}", "start it: windowping service start"))
    # A running unit whose state file stopped moving is worse than a stopped one.
    state_path = Path(config.general.state_file)
    if state_path.exists():
        try:
            updated = json.loads(state_path.read_text(encoding="utf-8")).get("updated_at")
        except (OSError, ValueError):
            updated = None
        if isinstance(updated, (int, float)):
            age = time.time() - updated
            limit = max(3 * config.general.tick_interval, 300.0)
            if age > limit:
                checks.append(
                    Check(
                        "watcher",
                        WARN,
                        f"no tick for {fmt_delta(age)}",
                        "the service is up but idle: check journalctl --user -u windowping",
                    )
                )
            else:
                checks.append(Check("watcher", OK, f"last tick {fmt_delta(age)} ago"))
    return checks


# -- entry point --------------------------------------------------------- #


def inspect(config: Config, *, clock_server: float | None = None) -> Report:
    report = Report()
    report.add(check_python())
    report.add(check_config(config))
    report.add(*check_paths(config))
    report.add(check_clock(server_now=clock_server))
    report.add(*check_providers(config))
    report.add(*check_binaries(config))
    report.add(*check_telegram(config))
    report.add(*check_service(config))
    return report


def run(config: Config, *, as_json: bool = False) -> int:
    report = inspect(config)
    print(report.json() if as_json else report.text())
    return report.exit_code
