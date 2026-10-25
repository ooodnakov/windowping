# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are
[semantic](https://semver.org/).

## [Unreleased]

The tunnel drops handshakes; the watcher used to treat each drop as an outage and
say so on Telegram, once per provider per minute.

### Added (card and buttons)

- **One live card** (`card.py`): a single Telegram message, edited in place, with
  inline buttons — Refresh, Ping, Stats, Schedule, Mute 8h.
- **`usage_interval`** (default `"30m"`): usage is read on a schedule instead of
  every 60s tick. A window reset, a failed ping, and the Refresh button force an
  early read. The tick itself stays at 60s.
- **`mute_hours`** (default `8`): the Mute button silences routine messages; an
  escalation is still delivered.
- **Batched pings**: several windows opening in one tick produce one message.
- **`/card` and the 🆕 button**: the card is deleted and re-sent at the bottom of
  the chat (edits cannot move a message). Cards are pinned on send.
- **`failed_ping_cooldown`** (default `"5m"`): after a failed ping the watcher
  waits before trying again, and forces a fresh usage read instead of trusting
  the cache.

### Added

- **Per-provider `schedule`** — `"mon-fri"`, `"mon-fri 07:00-23:30"`,
  `"weekends 10:00-02:00"` (wraps midnight), `"never"`, `"always"` (default).
  Gates pings only; usage is still read outside the schedule. Malformed values
  fail at config load.
- **`/schedule`** (и `/расписание`) in the bot: each provider's window and the
  next moment it opens.
- **Retries inside the tick** — connection-level failures are retried
  `ping_retries` times with doubling delay, and usage reads `read_retries` times.
  A provider that answers with an error (401, 500, bad payload) is never retried.
- **Error classification** (`errors.py`): `network` vs `provider`.

### Changed

- **One message per outage.** A failed ping now notifies on the first failure and
  at every `escalate_after` threshold, not on every tick; a recovered provider
  says so.
- **One network message per incident.** While the tunnel is down every provider
  fails at once, so network-class failures share a
  `network_notify_cooldown` (default 30 minutes) instead of sending N messages.

## [0.3.0] — 2026-10-23

### Added

- **`windowping stats`** and a daily digest. Every ping, failure, weekly stop and
  usage error is appended to `events.jsonl` next to the state file; `stats` reports
  windows opened, coverage hours, tokens, time spent and a per-provider breakdown,
  in text or `--json`, for any period. `/stats` in the bot, and one quiet summary per
  day after `[telegram] digest_at`.
- **`windowping doctor`** — read-only checks for the things that fail silently:
  config permissions, state directory, event log, clock skew against a real HTTP
  `Date`, every provider's usage endpoint, the CLI binaries a `ping_mode` needs, the
  bot token via `getMe`, quiet-hours and digest syntax, the systemd unit and whether
  the watcher ticked recently. Exit code 1 only on real failures.
- **Watchdog and escalation.** The unit now runs `Type=notify` with
  `WatchdogSec=300` and `RestartSec=5s`; the watcher sends `READY`, `WATCHDOG` after
  each tick and `STOPPING` on the way out, so systemd can tell "running" from "hung".
  `[general] escalate_after = 3` adds an explicit "needs a hand" message after
  repeated ping failures, pointing at `doctor`.
- **Kimi for Coding and MiniMax coding plan providers** (both opt-in). Kimi windows
  are identified by `duration × timeUnit` from the payload; MiniMax bills in aligned
  blocks, so its 5h window is the block spanning ≤ 7.5h and the reset is `end_time`.
  Ping endpoints are inferred from the OpenAI-compatible surfaces and unverified on
  a live plan — see the README caveat.
- **Several accounts of one provider.** `[providers.codex.accounts.work]` builds the
  provider once per account, each with its own credentials, state and windows, named
  `codex:work`; the base name still means "every account".

### Changed

- `http.py` sends a `User-Agent` that follows `__version__` instead of a hardcoded
  `0.1.0`.

### Fixed

- A ping recorded in the event log can no longer be lost to a timestamp that rounds
  a fraction of a millisecond into the future.
- `doctor` asked for a real clock source instead of reporting "no network" whenever
  the caller did not pass one.

## [0.2.1] — 2026-10-22

### Added

- **Quiet hours** for Telegram: `[telegram] quiet_hours = "12:00-08:00"` delivers
  notifications and replies with `disable_notification`, so the bot never makes a
  sound inside the configured local-time ranges. Ranges may wrap midnight, several
  can be comma-separated, and a malformed spec raises at startup instead of
  quietly leaving the phone loud.

### Fixed

- The polling thread no longer dies when Telegram drops a long-poll connection
  (`http.client.RemoteDisconnected` escaped the thread, and the bot went silent
  while the watcher kept pinging). Transport, JSON and per-update failures are now
  logged and retried with a capped backoff, and the update offset advances before
  handling so a poisoned message cannot replay forever.

## [0.2.0] — 2026-10-21

### Added

- **Claude Code provider** (`[providers.claude]`, opt-in). Usage comes from a
  read-only `GET /api/oauth/usage` with the Claude Code login (macOS Keychain or
  `~/.claude/.credentials.json`, `$CLAUDE_CONFIG_DIR` honoured), with a token
  refresh on 401. The ping drives one *interactive* `claude` turn on a pty — print
  mode is billed to agent credits and never starts a subscription window — under
  its own session id, with hooks, tools, MCP servers and CLAUDE.md disabled, and
  the transcript read to prove a real reply came back.
- **`ping_mode` for Codex**: `cli` (the `codex exec` path) or `api`, which posts a
  single Responses turn to the same backend the CLI uses with
  `max_output_tokens: 16`. Measured 16 tokens instead of ~12 000 per ping.
  `ping_fallback` retries through the CLI when the API path fails.
- **`ping_mode` for Claude**: `cli` (default) or `api`, a single 1-token
  `/v1/messages` call that also returns the fresh meter from the
  `anthropic-ratelimit-unified-5h-*` response headers.
- **`windowping service`** subcommands — `install`, `uninstall`, `start`, `stop`,
  `restart`, `enable`, `disable`, `status`, `logs`. The systemd unit is rendered
  from a template shipped inside the package, so a checkout and a pip install
  produce the same file.
- **Russian bot replies.** `[telegram] lang = "auto" | "en" | "ru"`; `auto`
  follows each sender's Telegram `language_code`, and notifications use the
  owner's last seen language. Everything else in the project is English.
- `docs/provider-research.md` — what the survey of coding subscriptions found,
  with evidence levels.

### Changed

- Telegram output is HTML: bold provider names, a monospace meter block, status
  icons (🟢 ok, 🟠 weekly exhausted, 🔴 error, ⚪️ no data), translated detail
  lines, and a plain-text fallback when Telegram rejects an entity.
- `pyproject.toml` follows PEP 639 (`license = "MIT"` plus `license-files`), with
  wider classifiers, project URLs and package data.

### Fixed

- GLM: `glm-4.5-flash` answers `200 OK` but never consumes coding-plan quota, so
  the default is now `glm-5.3-flash`.
- The watcher re-reads usage after a successful ping, so the notification says
  when the new window ends, and it logs decisions to the journal only when the
  state actually changes.

## [0.1.0] — 2026-10-21

First release: Codex, Command Code and GLM Coding Plan providers, the window
scheduler with its weekly guard, reset buffer, cooldown and registration grace,
a single TOML config, Telegram notifications and a `status` command.
