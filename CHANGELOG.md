# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are
[semantic](https://semver.org/).

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
