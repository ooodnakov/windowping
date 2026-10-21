"""Claude Code (Pro/Max plan) — OAuth usage endpoint + interactive ``claude`` ping.

Auth is the Claude Code CLI's own login: the macOS Keychain item
``Claude Code-credentials`` or ``~/.claude/.credentials.json`` elsewhere
(``$CLAUDE_CONFIG_DIR`` moves both, as it does for the CLI).  Usage is a
read-only hit on ``/api/oauth/usage``; a 401 first re-reads the store, since the
CLI may have refreshed in the meantime, and only then refreshes through the
CLI's OAuth client, writing the rotated tokens back so both tools stay in sync.

The ping is an *interactive* Claude Code session driven through a
pseudo-terminal.  Print mode (``claude -p``) is billed to Agent SDK / API
credits instead of the subscription, so it never starts a 5h window.  The
session is kept as bare as the CLI allows, and its transcript is read (the
local proof that a billable request went out) and then deleted.

Ported from wavever/CCLimitPing (MIT).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import ProviderConfig
from ..http import HttpError, request_json
from .base import PingResult, Usage, Window

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# Claude Code refreshes against platform.claude.com since 2.1.2xx.
OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_BETA = "oauth-2025-04-20"
KEYCHAIN_SERVICE = "Claude Code-credentials"
KEYCHAIN = "keychain"
FALLBACK_VERSION = "2.1.0"
# Model name Claude Code gives the error messages it writes itself.
SYNTHETIC_MODEL = "<synthetic>"

# The ping is a synthetic session: no CLAUDE.md of the directory it runs in,
# and no "ok" left in the prompt history the up arrow recalls there.
PING_ENV = {
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
}
# The user's hooks have no business firing for it, and a prompt suggestion is
# one more request after the reply.
PING_SETTINGS = '{"disableAllHooks":true,"promptSuggestionEnabled":false}'

# Print-mode flags the interactive CLI rejects; dropped from extra_args.
_PRINT_ONLY_FLAGS = frozenset({
    "-p", "--print", "--bare", "--init", "--maintenance", "--include-hook-events",
    "--include-partial-messages", "--replay-user-messages", "--prompt-suggestions",
    "--no-session-persistence",
})
_PRINT_ONLY_VALUE_FLAGS = frozenset({
    "--output-format", "--input-format", "--json-schema", "--max-turns",
    "--max-budget-usd", "--permission-prompt-tool", "--fallback-model",
})

_DENIALS = (
    "Your organization has disabled Claude subscription access for Claude Code",
    "OAuth authentication is currently not allowed for this organization",
    "oauth_org_not_allowed",
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_NON_TEXT_RE = re.compile(r"[^a-z0-9_]+")
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ACCOUNT_RE = re.compile(r'"acct"<blob>="([^"]*)"')


# --------------------------------------------------------------------------- #
# locations
# --------------------------------------------------------------------------- #


def config_dir() -> Path:
    """``$CLAUDE_CONFIG_DIR`` or ``~/.claude``: credentials and transcripts."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def global_config_path() -> Path:
    """``.claude.json`` (trusted folders) sits in the home dir unless moved."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    base = Path(configured).expanduser() if configured else Path.home()
    return base / ".claude.json"


def _secure_storage_dir() -> tuple[Path, bool]:
    """Where Claude Code keys its credentials, and whether that is non-default."""
    if "CLAUDE_SECURESTORAGE_CONFIG_DIR" in os.environ:
        value = os.environ["CLAUDE_SECURESTORAGE_CONFIG_DIR"]
        if not value:
            return Path.home() / ".claude", False
        return Path(value).expanduser(), True
    return config_dir(), bool(os.environ.get("CLAUDE_CONFIG_DIR", "").strip())


def keychain_service() -> str:
    """A non-default config dir gets its own Keychain item, as in Claude Code."""
    directory, custom = _secure_storage_dir()
    if not custom:
        return KEYCHAIN_SERVICE
    return f"{KEYCHAIN_SERVICE}-{hashlib.sha256(str(directory).encode()).hexdigest()[:8]}"


def credentials_path() -> Path:
    return _secure_storage_dir()[0] / ".credentials.json"


# --------------------------------------------------------------------------- #
# usage
# --------------------------------------------------------------------------- #


def _parse_ts(value) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def _window(block) -> Window:
    """``{utilization: 0..100, resets_at: ISO | null}``; null block = no limit."""
    if not isinstance(block, dict):
        return Window(enforced=False)
    pct = block.get("utilization")
    pct = max(0.0, min(100.0, float(pct))) if isinstance(pct, (int, float)) else None
    return Window(
        pct=pct,
        reset_at=_parse_ts(block.get("resets_at")),
        exceeded=(pct is not None and pct >= 100),
    )


def parse_usage(payload: dict) -> Usage:
    usage = Usage(provider="claude")
    usage.five = _window(payload.get("five_hour"))
    usage.weekly = _window(payload.get("seven_day"))
    usage.details.extend(_scoped_details(payload))
    return usage


def _scoped_details(payload: dict) -> list[str]:
    """The narrower caps beside the plan-wide ones, e.g. Opus' own weekly meter.

    ``limits`` is the server's own list (Claude Code renders it verbatim);
    older responses only carry ``seven_day_opus``-style keys.
    """
    details: list[str] = []
    rows = payload.get("limits")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("kind") or "")
            pct = row.get("percent")
            if not kind or kind in ("session", "weekly_all") or not isinstance(pct, (int, float)):
                continue
            scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
            label = ""
            for key in ("model", "surface"):
                block = scope.get(key)
                if isinstance(block, dict) and block.get("display_name"):
                    label = str(block["display_name"])
                    break
            if label and kind.startswith("weekly"):
                label += " weekly"
            details.append(f"{label or kind} {pct:.0f}%")
        return details
    for key, block in payload.items():
        if key in ("five_hour", "seven_day") or not key.startswith(("five_hour_", "seven_day_")):
            continue
        if not isinstance(block, dict) or not isinstance(block.get("utilization"), (int, float)):
            continue
        span = "weekly" if key.startswith("seven_day_") else "5h"
        details.append(f"{key.split('_', 2)[-1]} {span} {block['utilization']:.0f}%")
    return details


# --------------------------------------------------------------------------- #
# ping helpers
# --------------------------------------------------------------------------- #


@dataclass
class Timings:
    """Interactive ping pacing.

    The 5h window anchors when the submitted prompt's request is dispatched, so
    the TUI must render and settle before Enter, and the turn must run until its
    output goes quiet before ``/exit`` — quitting earlier cancels the request.
    """

    startup_timeout: float = 10.0
    startup_settle: float = 1.2
    turn_min: float = 4.0
    turn_quiet: float = 2.5
    turn_max: float = 45.0
    exit_grace: float = 5.0
    poll: float = 0.2


def normalized(text: str) -> str:
    """Lowercase alphanumerics only: survives ANSI, JSON and TUI line wrapping."""
    return _NON_TEXT_RE.sub(" ", _ANSI_RE.sub(" ", text).lower())


def access_denied(text: str) -> bool:
    plain = normalized(text)
    return any(normalized(denial) in plain for denial in _DENIALS)


def trust_prompt(text: str) -> bool:
    """Claude Code's workspace-trust dialog, whose default answer is "exit"."""
    compact = normalized(text).replace(" ", "")
    return "itrustthisfolder" in compact or "oneyoutrust" in compact


def plain_tail(text: str, limit: int = 200) -> str:
    plain = " ".join(_ANSI_RE.sub(" ", text).split())
    return plain[-limit:]


def flag_supported(help_text: str, flag: str) -> bool:
    """Whether an option line of ``claude --help`` declares ``flag``.

    A mention inside another option's description does not count.
    """
    pattern = r"(?m)^ {2,4}(?:-[A-Za-z], )?(?:--[A-Za-z0-9-]+, )*" + re.escape(flag) + r"(?:[ =,]|$)"
    return re.search(pattern, help_text or "") is not None


def _flag_name(arg: str) -> tuple[str, bool]:
    if arg.startswith("--") and "=" in arg:
        return arg.split("=", 1)[0], True
    return arg, False


def interactive_args(extra: list[str]) -> list[str]:
    """Drop print-mode flags (and their values) the interactive CLI rejects."""
    out: list[str] = []
    skip_value = False
    for arg in extra:
        if skip_value:
            skip_value = False
            continue
        flag, inline = _flag_name(arg)
        if flag in _PRINT_ONLY_VALUE_FLAGS:
            skip_value = not inline
            continue
        if flag in _PRINT_ONLY_FLAGS:
            continue
        out.append(arg)
    return out


def isolation_args(help_text: str, session_id: str | None, extra: list[str]) -> list[str]:
    """Flags that keep the ping bare, each only when the installed CLI has it.

    ``--session-id`` names the session so its transcript can be found and
    deleted; ``--strict-mcp-config`` starts no MCP servers and ``--tools ""``
    sends no tool definitions.  A flag the user already passes is left to them.
    """
    user_flags = {_flag_name(arg)[0] for arg in extra}
    out: list[str] = []

    def add(flag: str, *values: str) -> None:
        if flag not in user_flags and flag_supported(help_text, flag):
            out.extend((flag, *values))

    if session_id:
        add("--session-id", session_id)
    add("--settings", PING_SETTINGS)
    add("--strict-mcp-config")
    add("--tools", "")
    return out


def trusted_dirs(path: Path) -> set[str]:
    """Folders Claude Code has been told to trust, from ``.claude.json``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        return set()
    return {
        name
        for name, entry in projects.items()
        if isinstance(entry, dict) and entry.get("hasTrustDialogAccepted") is True
    }


def borrowable(directory: str | Path) -> bool:
    """A trusted folder can host the ping when it exists and has no project
    settings that could route the request elsewhere."""
    path = Path(directory)
    if not path.is_absolute() or not path.is_dir():
        return False
    for name in ("settings.json", "settings.local.json"):
        candidate = path / ".claude" / name
        if candidate.exists() or candidate.is_symlink():
            return False
    return True


def pick_ping_dir(workdir: Path, trusted: set[str], can_borrow: bool) -> Path:
    """Run in ``workdir`` when Claude Code trusts it; otherwise borrow a trusted
    folder, so the trust dialog (which a ping cannot answer) never comes up.

    Borrowing is only allowed when the ping's transcript will be deleted, so
    it passes through somebody's project without a trace.  The home directory,
    whose trust Claude Code does not keep, is the usual reason to borrow.
    """
    workdir = Path(workdir).expanduser()
    if str(workdir) in trusted or os.path.realpath(workdir) in trusted or not can_borrow:
        return workdir
    for candidate in sorted(trusted):
        if borrowable(candidate):
            return Path(candidate)
    return workdir


@dataclass
class Transcript:
    answered: bool = False
    model: str | None = None
    tokens: int | None = None
    error: str | None = None


def _transcript_files(root: Path, session_id: str) -> list[Path]:
    if not _SESSION_ID_RE.match(session_id or ""):
        return []
    return sorted((Path(root) / "projects").glob(f"*/{session_id}.jsonl"))


def read_transcript(root: Path, session_id: str) -> Transcript | None:
    """What the ping's session recorded: a real reply, or Claude Code's own error.

    A reply from the API carries the model and token usage; the errors the CLI
    writes itself (auth failures, limits) are marked ``<synthetic>``.
    """
    files = _transcript_files(root, session_id)
    if not files:
        return None
    found = Transcript()
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "assistant":
                continue
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            model = message.get("model")
            if entry.get("isApiErrorMessage") or model == SYNTHETIC_MODEL:
                found.error = _message_text(message) or "Claude Code reported an API error"
                continue
            found.answered = True
            found.model = model if isinstance(model, str) and model else found.model
            usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
            counts = [
                usage.get(key)
                for key in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                    "output_tokens",
                )
            ]
            numbers = [n for n in counts if isinstance(n, int)]
            if numbers:
                found.tokens = (found.tokens or 0) + sum(numbers)
    return found


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()[:300]
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                return block["text"].strip()[:300]
    return ""


def remove_transcript(root: Path, session_id: str) -> None:
    """Delete the ping's transcript and the per-session folder beside it.

    Only a UUID is ever globbed, so nothing but this ping's session can match.
    """
    for path in _transcript_files(root, session_id):
        try:
            path.unlink()
        except OSError:
            pass
        shutil.rmtree(path.with_suffix(""), ignore_errors=True)


def drive_session(
    command: list[str],
    *,
    cwd: Path,
    env: dict,
    timings: Timings | None = None,
    budget: float = 180.0,
) -> tuple[int | None, str]:
    """Run an interactive CLI on a pty: settle, press Enter, wait for quiet, /exit.

    Returns the exit code (None when the session had to be killed) and the tail
    of what it printed.  POSIX only.
    """
    import fcntl
    import select
    import signal
    import struct
    import termios

    timings = timings or Timings()
    master, slave = os.openpty()
    try:
        # A wide screen keeps the TUI from wrapping the messages we match on.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 160, 0, 0))
    except OSError:
        pass
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
    except OSError:
        os.close(master)
        os.close(slave)
        raise
    os.close(slave)

    tail = bytearray()
    last_output = 0.0
    closed = False
    end = time.monotonic() + budget

    def pump(wait: float) -> None:
        nonlocal last_output, closed
        if closed:
            time.sleep(wait)
            return
        ready, _, _ = select.select([master], [], [], max(0.0, wait))
        if not ready:
            return
        try:
            chunk = os.read(master, 65536)
        except OSError:  # EIO once the session side is gone
            chunk = b""
        if not chunk:
            closed = True
            return
        tail.extend(chunk)
        del tail[:-16384]
        last_output = time.monotonic()

    def phase(max_wait: float, ready) -> bool:
        """Pump output until ``ready(idle, elapsed)``; True if the session exited."""
        start = time.monotonic()
        stop = min(start + max_wait, end)
        while True:
            if proc.poll() is not None:
                pump(0)
                return True
            now = time.monotonic()
            if now >= stop:
                return False
            if last_output and ready(now - last_output, now - start):
                return False
            pump(min(timings.poll, stop - now))

    def send(data: bytes) -> None:
        try:
            os.write(master, data)
        except OSError:
            pass

    try:
        exited = phase(timings.startup_timeout, lambda idle, _: idle >= timings.startup_settle)
        if not exited:
            # Submit the prompt: this request is what anchors the window.
            send(b"\r")
            exited = phase(
                timings.turn_max,
                lambda idle, elapsed: elapsed >= timings.turn_min and idle >= timings.turn_quiet,
            )
        if not exited:
            send(b"/exit\r")
            phase(timings.exit_grace, lambda idle, elapsed: False)
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        os.close(master)
    code = proc.returncode
    return (code if code is not None and code >= 0 else None), tail.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# provider
# --------------------------------------------------------------------------- #


class ClaudeProvider:
    name = "claude"
    title = "Claude Code"

    def __init__(self, cfg: ProviderConfig, *, timeout: float = 20.0, ping_timeout: float = 180.0, workdir: Path | None = None):
        self.cfg = cfg
        self.timeout = timeout
        self.ping_timeout = ping_timeout
        self.workdir = Path(workdir or Path.home())
        self.model = str(cfg.get("model") or "haiku")
        self.prompt = str(cfg.get("prompt") or "ok")
        self.bin = str(cfg.get("bin") or "claude")
        self.usage_url = str(cfg.get("usage_url") or USAGE_URL)
        self.auth_file = cfg.get("auth_file")
        self.ping_dir = cfg.get("ping_dir")
        self.extra_args = [str(arg) for arg in (cfg.get("extra_args") or [])]
        # The usage endpoint throttles hard (429); the watcher ticks every
        # minute, so reads are cached unless a cached reset has passed.
        self.read_interval = cfg.num("read_interval", 300.0)
        self.timings = Timings()
        self._oauth: dict | None = None
        self._source: str | None = None
        self._cache: tuple[float, Usage] | None = None
        self._version: str | None = None
        self._help: str | None = None

    # -- auth -------------------------------------------------------------- #

    def _store_path(self) -> Path:
        if self.auth_file:
            return Path(str(self.auth_file)).expanduser()
        return credentials_path()

    def _use_keychain(self) -> bool:
        return sys.platform == "darwin" and not self.auth_file

    def _read_store(self) -> dict:
        """The whole credentials document, from the Keychain or the file."""
        if self._use_keychain():
            try:
                proc = subprocess.run(
                    ["security", "find-generic-password", "-s", keychain_service(), "-w"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                proc = None
            if proc is not None and proc.returncode == 0 and proc.stdout.strip():
                try:
                    data = json.loads(proc.stdout.strip())
                except ValueError:
                    raise RuntimeError("Claude Code Keychain credentials are not valid JSON") from None
                self._source = KEYCHAIN
                return data if isinstance(data, dict) else {}
        path = self._store_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(
                f"cannot read Claude Code credentials {path}: {exc} — run `claude` and log in"
            ) from None
        except ValueError:
            raise RuntimeError(f"{path} is not valid JSON") from None
        self._source = str(path)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _oauth_block(data: dict) -> dict:
        """Credentials are stored as ``{"claudeAiOauth": {...}}`` or flat."""
        inner = data.get("claudeAiOauth")
        return inner if isinstance(inner, dict) else data

    def _load(self) -> dict:
        self._oauth = self._oauth_block(self._read_store())
        return self._oauth

    def token(self) -> str:
        oauth = self._oauth if self._oauth is not None else self._load()
        value = oauth.get("accessToken")
        if not isinstance(value, str) or not value:
            raise RuntimeError("no Claude Code OAuth token — run `claude` and log in")
        return value

    def reload(self) -> str:
        """Re-read the store: the CLI may have refreshed since we last looked."""
        self._load()
        return self.token()

    def refresh(self) -> str:
        """Exchange the refresh token, persisting rotated tokens for the CLI."""
        oauth = self._oauth if self._oauth is not None else self._load()
        refresh_token = oauth.get("refreshToken")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise RuntimeError("Claude Code auth has no refresh token — run `claude` and log in")
        try:
            payload = request_json(
                OAUTH_TOKEN_URL,
                method="POST",
                body={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": OAUTH_CLIENT_ID,
                },
                timeout=self.timeout,
            )
        except HttpError as exc:
            raise RuntimeError(
                f"Claude token refresh failed ({exc}) — run `claude` and log in again"
            ) from None
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise RuntimeError("Claude token refresh returned no access_token")
        rotated = {"accessToken": access}
        if payload.get("refresh_token"):
            rotated["refreshToken"] = payload["refresh_token"]
        if isinstance(payload.get("expires_in"), (int, float)):
            rotated["expiresAt"] = int((time.time() + payload["expires_in"]) * 1000)
        self._oauth = {**oauth, **rotated}
        self._persist(rotated)
        return access

    def _persist(self, rotated: dict) -> None:
        """Write rotated tokens back, re-reading first so nothing the CLI wrote
        meanwhile (MCP OAuth entries share the file) is lost.  Best effort."""
        try:
            data = self._read_store()
        except RuntimeError:
            data = {}
        if isinstance(data.get("claudeAiOauth"), dict) or not data:
            data["claudeAiOauth"] = {**data.get("claudeAiOauth", {}), **rotated}
        else:
            data.update(rotated)
        blob = json.dumps(data)
        try:
            if self._source == KEYCHAIN:
                self._keychain_write(blob)
                return
            path = self._store_path()
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(blob, encoding="utf-8")
            os.chmod(tmp, 0o600)
            tmp.replace(path)
        except (OSError, subprocess.SubprocessError):
            pass

    def _keychain_write(self, blob: str) -> None:
        service = keychain_service()
        found = subprocess.run(
            ["security", "find-generic-password", "-s", service],
            capture_output=True,
            text=True,
            timeout=10,
        )
        match = _ACCOUNT_RE.search(found.stdout + found.stderr)
        command = ["security", "add-generic-password", "-U", "-s", service, "-w", blob]
        if match:
            command += ["-a", match.group(1)]
        subprocess.run(command, capture_output=True, timeout=10, check=True)

    def plan(self) -> str | None:
        value = (self._oauth or {}).get("subscriptionType")
        return value if isinstance(value, str) and value else None

    # -- cli --------------------------------------------------------------- #

    def _cli_output(self, *args: str, timeout: float = 10.0) -> str:
        try:
            proc = subprocess.run(
                [self.bin, *args], capture_output=True, text=True, timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return proc.stdout if proc.returncode == 0 else ""

    def version(self) -> str:
        if self._version is None:
            words = self._cli_output("--version", timeout=5.0).split()
            self._version = words[0] if words else FALLBACK_VERSION
        return self._version

    def help_text(self) -> str:
        if self._help is None:
            self._help = self._cli_output("--help")
        return self._help

    # -- provider interface ------------------------------------------------ #

    def _get_usage(self, token: str) -> dict:
        return request_json(
            self.usage_url,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": OAUTH_BETA,
                "User-Agent": f"claude-code/{self.version()}",
            },
            timeout=self.timeout,
        )

    def _fetch_usage(self) -> dict:
        token = self.token()
        try:
            return self._get_usage(token)
        except HttpError as exc:
            if exc.status != 401:
                raise
        reloaded = self.reload()
        if reloaded != token:
            try:
                return self._get_usage(reloaded)
            except HttpError as exc:
                if exc.status != 401:
                    raise
        return self._get_usage(self.refresh())

    def usage(self) -> Usage:
        now = time.time()
        cached = rolled = None
        if self._cache is not None:
            read_at, cached = self._cache
            rolled = any(
                window.reset_at is not None and now >= window.reset_at
                for window in (cached.five, cached.weekly)
            )
            if now - read_at < self.read_interval and not rolled:
                return cached
        try:
            payload = self._fetch_usage()
        except HttpError as exc:
            # Throttled: a snapshot whose resets are all still ahead is as good.
            if exc.status == 429 and cached is not None and not rolled:
                return cached
            raise
        usage = parse_usage(payload)
        usage.plan = self.plan()
        self._cache = (now, usage)
        return usage

    def ping_command(self, session_id: str | None = None) -> list[str]:
        extra = interactive_args(self.extra_args)
        command = [self.bin]
        if self.model:
            command += ["--model", self.model]
        command += isolation_args(self.help_text(), session_id, extra)
        command += extra
        # "--" ends the options so a variadic one (--tools) cannot eat the prompt.
        command += ["--", self.prompt]
        return command

    def ping_cwd(self, can_borrow: bool) -> Path:
        if self.ping_dir:
            return Path(str(self.ping_dir)).expanduser()
        return pick_ping_dir(self.workdir, trusted_dirs(global_config_path()), can_borrow)

    def ping(self) -> PingResult:
        """Start a window with one interactive turn, then prove it from the transcript."""
        self._cache = None  # whatever happens next, the next read must be fresh
        model = self.model or None
        binary = shutil.which(self.bin) or (self.bin if Path(self.bin).exists() else None)
        if not binary:
            return PingResult(ok=False, error=f"`{self.bin}` not found in PATH", model=model)
        if not hasattr(os, "openpty"):
            return PingResult(
                ok=False,
                error="the Claude ping drives an interactive session and needs a POSIX pty (Linux/macOS)",
                model=model,
            )
        session_id = str(uuid.uuid4())
        command = self.ping_command(session_id)
        command[0] = binary
        owned = session_id in command
        cwd = self.ping_cwd(can_borrow=owned)
        env = {**os.environ, **PING_ENV}
        env.setdefault("TERM", "xterm-256color")
        env.pop("CLAUDECODE", None)  # not a child of whatever session launched windowping

        started = time.monotonic()
        try:
            code, output = drive_session(
                command, cwd=cwd, env=env, timings=self.timings, budget=self.ping_timeout
            )
        except OSError as exc:
            return PingResult(ok=False, error=f"cannot run claude: {exc}", model=model)
        finally:
            # Read before deleting, and delete even when the run blew up.
            transcript = read_transcript(config_dir(), session_id) if owned else None
            if owned:
                remove_transcript(config_dir(), session_id)
        elapsed = time.monotonic() - started

        if transcript is not None and transcript.answered:
            return PingResult(
                ok=True,
                seconds=elapsed,
                model=transcript.model or model,
                tokens=transcript.tokens,
            )
        if access_denied(output):
            return PingResult(
                ok=False,
                seconds=elapsed,
                model=model,
                error="Claude subscription access is unavailable (plan expired, or an admin "
                "disabled Claude Code for the organization)",
            )
        if trust_prompt(output):
            return PingResult(
                ok=False,
                seconds=elapsed,
                model=model,
                error=f"claude asked whether to trust {cwd} and a ping cannot answer that, so "
                "nothing was sent: run `claude` there once and trust it, or point "
                "providers.claude.ping_dir at a folder Claude Code already trusts",
            )
        if transcript is not None and transcript.error:
            return PingResult(ok=False, seconds=elapsed, model=model, error=transcript.error)
        if owned:
            tail = plain_tail(output)
            return PingResult(
                ok=False,
                seconds=elapsed,
                model=model,
                error="no request reached Claude"
                + (f" (exit code {code})" if code else "")
                + (f": {tail}" if tail else ""),
            )
        # An old CLI without --session-id leaves no transcript we can name, so
        # a clean session is the best evidence available.
        return PingResult(ok=True, seconds=elapsed, model=model, detail="unverified: no --session-id")


def build(cfg: ProviderConfig, *, general=None) -> ClaudeProvider:
    return ClaudeProvider(
        cfg,
        timeout=getattr(general, "read_timeout", 20.0),
        ping_timeout=getattr(general, "ping_timeout", 180.0),
        workdir=getattr(general, "workdir", Path.home()),
    )
