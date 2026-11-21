# Config Reference

All configuration lives in a single TOML file: `~/.config/windowping/config.toml` (created with mode `600` by `windowping config init`).

You can override the path with `--config <path>` or the `WINDOWPING_CONFIG` environment variable. State and event logs default to `~/.local/state/windowping/` (or `$WINDOWPING_STATE` for the state file).

Duration values accept strings such as `"90s"`, `"5m"`, `"2h"`, `"1d"`, or bare numbers (seconds).

## Complete Example Config

```toml
# windowping — keep 5h rate-limit windows back-to-back.
# One file for everything: scheduling, providers, Telegram.

[general]
# Stop pinging a provider once its weekly meter is at/above this fraction.
weekly_threshold = 0.99
# Wait this long after a window's reset before pinging (rollover safety).
reset_buffer = "5m"
# Never re-ping the same provider within this window.
cooldown = "10m"
# After a ping that has not shown up in the usage meter yet, wait this long.
register_grace = "30m"
# How often the watcher loop wakes up.
tick_interval = "60s"
# Wall clock budget for one provider ping.
ping_timeout = "180s"
# Directory the Codex and Claude pings run in.
workdir = "~"
# Failed pings in a row before an explicit "needs a hand" message (0 = never).
escalate_after = 3
# Connection errors are retried inside the same tick (delays double: 5s, 10s, ...).
ping_retries = 2
read_retries = 1
retry_delay = "5s"
# One "network is down" message per incident, not one per provider per tick.
network_notify_cooldown = "30m"
# Usage is read on this cadence instead of every tick; Refresh and resets read early.
usage_interval = "30m"
# Wait after a failed ping before trying again.
failed_ping_cooldown = "5m"
# Hours the Mute button silences routine messages.
mute_hours = 8
# One live card message edited in place instead of a stream of statuses.
card = true

# Paths are optional; these are the defaults.
# state_file = "~/.local/state/windowping/state.json"
# history_file = "~/.local/state/windowping/events.jsonl"

[providers.codex]
enabled = true
# "" = pick the cheapest model the Codex catalog offers at ping time.
model = ""
effort = "low"
prompt = "ok"
# "cli" (~12k tokens via codex exec) or "api" (~16 tokens via ChatGPT backend).
ping_mode = "cli"
ping_fallback = true
# bin = "codex"
# auth_file = "~/.codex/auth.json"
# config_file = "~/.codex/config.toml"
# models_cache = "~/.codex/models_cache.json"

[providers.commandcode]
enabled = true
model = "deepseek/deepseek-v4.1-flash"
prompt = "ok"
base_url = "https://api.commandcode.ai"
# auth_file = "~/.commandcode/auth.json"

[providers.glm]
enabled = true
schedule = "mon-fri"
# Coding-plan tier model: legacy models (glm-4.5-flash) never start a 5h window.
model = "glm-5.3-flash"
prompt = "ok"
base_url = "https://api.z.ai/api/coding/paas/v4"
usage_url = "https://api.z.ai/api/monitor/usage/quota/limit"
# api_key = ""
api_key_env = "GLM_API_KEY"
env_file = "~/.hermes/.env"

[providers.claude]
enabled = false
model = "haiku"
prompt = "ok"
ping_mode = "cli"            # "cli" = one interactive turn | "api" = 1-token /v1/messages
ping_fallback = true
# api_model = "claude-haiku-4-5"
read_interval = "5m"
# ping_dir = "~/Projects/some-trusted-repo"
# extra_args = ["--effort", "low"]
# bin = "claude"
# auth_file = "~/.claude/.credentials.json"   # default: Keychain on macOS

[providers.kimi]
enabled = false
model = "kimi-k2-turbo-preview"
prompt = "ok"
api_key_env = "KIMI_API_KEY"
# api_key = ""
# base_url = "https://api.kimi.com/coding/v1"
# usage_url = "https://api.kimi.com/coding/v1/usages"
# env_file = "~/.hermes/.env"

[providers.minimax]
enabled = false
model = "MiniMax-M2"
ping_path = "/text/chatcompletion_v2"
prompt = "ok"
api_key_env = "MINIMAX_API_KEY"
# api_key = ""
# base_url = "https://api.minimax.io/v1"      # or https://api.minimaxi.com/v1
# usage_url = "https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains"

[telegram]
enabled = false
bot_token = ""
bot_token_env = "WINDOWPING_BOT_TOKEN"
chat_id = 0
notify_events = ["ping", "error", "weekly", "digest", "escalate"]
poll = false
# allow_chat_ids = [298465764]
lang = "auto"                # "auto" | "en" | "ru"
silent = false
quiet_hours = ""
digest_at = ""
```

## Path Overrides & Defaults

Paths (`auth_file`, `models_cache`, `config_file`, `env_file`, `state_file`, `history_file`) all have sensible defaults and can be overridden per section. Secrets may be written inline (the file is created with mode `600` and should stay that way) or referenced through `*_env` / `env_file`.

## Several Accounts of One Provider

Two ChatGPT logins, two GLM keys, work plus personal — `accounts` turns each into its own instance with its own credentials, state, and windows:

```toml
[providers.codex]
enabled = true
ping_mode = "api"

[providers.codex.accounts.work]
auth_file = "~/.codex-work/auth.json"

[providers.codex.accounts.personal]
auth_file = "~/.codex/auth.json"     # this is also the default path
```

Each account inherits every key from the parent provider section and may override any of them (`auth_file`, `api_key`, `model`, `ping_mode`, `schedule`, …). Instances are named `codex:work` and `codex:personal`:

```sh
windowping status            # both accounts, on their own rows
windowping status codex      # both — the base name means "every account"
windowping status codex:work # just that one
windowping ping codex:work
```

`/status codex` works the same way in the Telegram bot. An account with `enabled = false` is skipped without touching the others.
