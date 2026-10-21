# windowping

Keep your **Codex**, **Command Code**, **GLM Coding Plan** and **Claude Code**
5-hour rate-limit windows back-to-back.

All four providers run on rolling 5h windows (plus a weekly cap). A fresh 5h
window does **not** start when the previous one resets — it starts when you send
the first billable request. If that happens three hours later, those three hours
are wasted and your schedule drifts for the rest of the day.

`windowping` watches each provider's reset time and fires one tiny request
through the provider's own endpoint right after rollover, so the next window
starts immediately.

```
✓ Codex: window opened (1.9s, 16 tokens)
gpt-5.6-luna · 5h window reset at Wed 19:52 MSK
```

Pure Python 3.11+, standard library only, no dependencies, no telemetry.

## What it does

| Job | Mechanism | Cost |
|-----|-----------|------|
| Read usage & reset time | each provider's own usage endpoint (zero quota) | free, never starts a window |
| Start the next window | one minimal billable request (`max_tokens=1`, `codex exec --ephemeral`, or one interactive Claude Code turn) | a sliver of quota — the whole point |

Safety rails, all configurable:

- **weekly guard** — stop pinging once the weekly meter is at/above
  `weekly_threshold` (default 99%): more pings cannot help until it resets;
- **reset buffer** — wait `reset_buffer` (default 5m) past the reset before
  pinging, so a clock skew cannot land the request in the old window;
- **cooldown** — never re-ping the same provider within `cooldown` (default 10m);
- **register grace** — if a ping has not shown up in the usage meter yet, wait
  up to `register_grace` (default 30m) instead of pinging again;
- **once per window** — a reset that was already pinged is never pinged twice,
  even across restarts (state file).

## Supported providers

| Provider | Usage (free) | Ping (billable) | Auth |
|---|---|---|---|
| **Codex** | `GET chatgpt.com/backend-api/wham/usage` | `POST …/backend-api/codex/responses` (api mode, ~16 tokens) or `codex exec --ephemeral --json` (cli mode) | OAuth in `~/.codex/auth.json` |
| **Command Code** | `GET api.commandcode.ai/alpha/billing/credits` | `POST …/provider/v1/chat/completions` | API key in `~/.commandcode/auth.json` |
| **GLM Coding Plan** | `GET api.z.ai/api/monitor/usage/quota/limit` | `POST api.z.ai/api/coding/paas/v4/chat/completions` | `GLM_API_KEY` |
| **Claude Code** | `GET api.anthropic.com/api/oauth/usage` | one interactive `claude` turn on a pty (see [Claude ping](#claude-ping)) | Claude Code login (Keychain / `~/.claude/.credentials.json`) |

The Codex OAuth token is refreshed automatically through the same client the
Codex CLI uses, and rotated tokens are written back to `~/.codex/auth.json`, so
both tools stay in sync.

> **GLM note:** only coding-plan tiers count. Legacy models such as
> `glm-4.5-flash` answer `200 OK` but never touch the plan's quota, so they never
> start a window. Keep `model` on a coding tier (`glm-5.3-flash` by default).

### Codex ping modes

Two ways to start a Codex window, chosen with `[providers.codex] ping_mode`:

| mode | what happens | measured cost |
|---|---|---|
| `cli` (default) | `codex exec --ephemeral --json …` — the official CLI, which injects its whole agent prompt | ~12 000 input tokens per ping |
| `api` | one raw `POST /backend-api/codex/responses` with a one-message input, `max_output_tokens = 16` | **16 tokens** (11 in / 5 out), ~1.2 s |

`api` speaks the same backend endpoint the CLI uses and authenticates with the
same OAuth token, so it is billed against the subscription. It is an internal
ChatGPT endpoint, though, not the documented public API: it can change without
notice, and `ping_fallback = true` (the default) keeps window chaining alive by
retrying through `codex exec` if the raw request fails. Measured on
`codex-cli 0.163.0`.

> Requests below `max_output_tokens = 16` are rejected outright
> (`integer_below_min_value`), and the meter is an integer percentage, so a
> 16-token ping will not visibly move it.

### Claude ping

Claude Code (Pro / Max) is opt-in: set `[providers.claude] enabled = true`.

- **Usage** is a read-only `GET /api/oauth/usage` with the Claude Code login
  (the macOS Keychain item `Claude Code-credentials`, else
  `~/.claude/.credentials.json`; `$CLAUDE_CONFIG_DIR` is honoured). On a 401 the
  store is re-read first, since the CLI may have refreshed it, and only then is
  the token refreshed through Claude Code's own OAuth client and written back.
  The endpoint throttles hard, so a read is reused for `read_interval` (default
  5m) unless one of its resets has passed, and a 429 falls back to that read.
- **Ping** is one *interactive* `claude --model haiku -- ok` turn on a
  pseudo-terminal. Print mode (`claude -p`) is billed to Agent SDK / API
  credits, not the subscription, so it never starts a window. The session runs
  under its own `--session-id`, with hooks and prompt suggestions off
  (`--settings`), no MCP servers (`--strict-mcp-config`), no tools
  (`--tools ""`), no CLAUDE.md and no prompt-history entry, each flag only when
  the installed CLI lists it. Its transcript is read to prove that a real reply
  came back (model and tokens, or Claude Code's own error), then deleted, so
  pings never pile up in `claude --resume`.
- **Folder:** Claude Code asks whether to trust an unknown folder, and a ping
  cannot answer. So it runs in `workdir` only when Claude Code trusts it, and
  otherwise borrows a trusted folder that has no `.claude/settings*.json`. Pin
  one with `ping_dir`.
- The ping needs a POSIX pty (Linux / macOS); `status` works everywhere.

### Claude API ping (opt-in)

`ping_mode = "api"` skips the pty and posts one message instead:

```
POST https://api.anthropic.com/v1/messages
Authorization: Bearer <oauth token>      anthropic-beta: oauth-2025-04-20
anthropic-version: 2023-06-01            User-Agent: claude-code/<version>

{"model": "claude-haiku-4-5", "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]}
```

This is the shape of Claude Code's own startup prefetch — a single turn, a single
output token, a fraction of a cent. The response carries
`anthropic-ratelimit-unified-5h-{utilization,reset}`, so one ping also returns the
fresh meter reading and the new reset time.

> **Unverified:** whether a raw `/v1/messages` call on the subscription OAuth
> token anchors a new 5h window has not been measured on a live account. The
> default stays `cli` for that reason; with `ping_fallback = true` a failing API
> ping retries through the CLI, so windows keep chaining either way. If you want
> to test it: set `ping_mode = "api"`, wait for a reset, and compare
> `five_hour.resets_at` in `windowping status` before and after.

> **Heads-up:** `/api/oauth/usage` is an internal endpoint, not a public API,
> and Anthropic's terms reserve subscription OAuth tokens for Claude Code and
> Claude.ai. windowping uses the token only to read the meter (and refresh it on
> a 401); the default billable ping goes through the official CLI. The opt-in
> `ping_mode = "api"` is the one place a raw request is sent with that token —
> decide for yourself whether that is acceptable for your account.

Ported from [wavever/CCLimitPing](https://github.com/wavever/CCLimitPing) (MIT).

## Install

```sh
git clone https://github.com/ooodnakov/windowping.git ~/Projects/windowping
cd ~/Projects/windowping
./install.sh                 # ~/.local/bin/windowping + systemd user unit
windowping config init       # write ~/.config/windowping/config.toml
$EDITOR ~/.config/windowping/config.toml
windowping status            # live meters
windowping ping --dry-run    # what a ping would send
```

`install.sh` is optional — the tool is a plain Python package:

```sh
PYTHONPATH=$PWD python3 -m windowping status
```

### From PyPI

```sh
pipx install windowping        # or: pip install --user windowping
windowping config init
windowping service install
```

## Usage

```sh
windowping status                 # 5h + weekly meters, reset countdowns
windowping status glm             # one provider
windowping status --json          # machine-readable
windowping ping                   # ping every enabled provider now
windowping ping codex             # one provider
windowping ping --dry-run         # print, send nothing
windowping tick                   # one scheduler pass (cron friendly)
windowping tick --dry-run
windowping watch                  # run the watcher in the foreground
windowping watch --no-bot         # ...without the Telegram bot thread
windowping bot                    # Telegram command bot only
windowping notify-test            # send one test message
windowping config init|path|show
windowping service install|uninstall|status|logs
windowping service start|stop|restart|enable|disable
```

Aliases: `status`/`s`, `ping`/`p`, `watch`/`w`, `config`/`c`.

## Config

One file: `~/.config/windowping/config.toml` (created with mode `600`).
Override the path with `--config` or `WINDOWPING_CONFIG`.

```toml
[general]
weekly_threshold = 0.99      # stop pinging at this weekly fraction
reset_buffer = "5m"          # wait past the reset before pinging
cooldown = "10m"             # minimum gap between pings per provider
register_grace = "30m"       # wait for a ping to appear in the usage meter
tick_interval = "60s"        # watcher wake-up interval
ping_timeout = "180s"
workdir = "~"                # cwd for the codex and claude pings

[providers.codex]
enabled = true
model = ""                   # "" = cheapest model in the Codex catalog
effort = "low"
prompt = "ok"
ping_mode = "cli"            # "cli" = codex exec (~12k tokens) | "api" = raw response (~16)
ping_fallback = true         # api mode: retry through the CLI if the API path fails

[providers.commandcode]
enabled = true
model = "deepseek/deepseek-v4.1-flash"
prompt = "ok"

[providers.glm]
enabled = true
model = "glm-5.3-flash"
prompt = "ok"
api_key_env = "GLM_API_KEY"  # falls back to api_key = "..."

[providers.claude]
enabled = false              # opt-in, see "Claude ping"
model = "haiku"
prompt = "ok"
ping_mode = "cli"            # "cli" = one interactive turn | "api" = one 1-token message
ping_fallback = true         # api mode: retry through the CLI if it fails
read_interval = "5m"         # reuse a usage read: the endpoint throttles
# ping_dir = "~/Projects/x"  # a folder Claude Code trusts

[telegram]
enabled = false
bot_token = ""               # or bot_token_env = "WINDOWPING_BOT_TOKEN"
chat_id = 0
notify_events = ["ping", "error", "weekly"]
poll = false                 # answer /status and /ping in the bot
lang = "auto"                # "auto" (follow the sender) | "en" | "ru"
```

Paths (`auth_file`, `models_cache`, `env_file`, `state_file`) all have sensible
defaults and can be overridden per section.

## Telegram

Two independent pieces, both optional:

1. **Notifications** — one message per transition: window opened, ping failed,
   weekly cap exhausted, connection recovered. Only transitions are sent, so a
   healthy day is silent. `bot_token` + `chat_id` is enough; `poll` can stay off.
2. **Commands** — with `poll = true` the watcher also long-polls `getUpdates`
   and answers `/status`, `/ping`, `/ping glm`, `/help`. Replies are restricted
   to `allow_chat_ids` (defaults to `chat_id`). Bare words work too: `status`,
   `ping`.

The bot speaks **English and Russian**. `[telegram] lang = "auto"` (default)
follows the sender's Telegram `language_code`, so the same deployment answers a
Russian client in Russian and an English one in English; `"en"` or `"ru"` pins
everything. Notifications follow the owner's last seen language. The rest of the
project — CLI output, docs, code — is English only.

**Quiet hours.** Telegram has no server-side schedule, but every message can be
sent with `disable_notification` — delivered, just silent. Set the ranges in
local time and the bot stops buzzing inside them (replies included):

```toml
[telegram]
quiet_hours = "12:00-08:00"          # wraps midnight
# quiet_hours = "23:00-07:00,13:00-14:00"   # several ranges
```

A malformed spec fails at startup instead of silently leaving the phone loud.
`silent = true` still forces silence around the clock.

Replies are Telegram HTML: provider names in bold, meters in a monospace
`<pre>` block, status icons per provider (🟢 ok, 🟠 weekly exhausted, 🔴 error,
⚪️ no data). If Telegram rejects an entity, the message is re-sent as plain text
instead of being dropped:

```
🟢 codex · plus
5h      █████████░  92%    2h44m
weekly  ███░░░░░░░  33%     6d6h
3 reset credit(s) available
```

The same block for a client whose Telegram language is Russian:

```
🟢 codex · plus
5h      █████████░  92%    2h44m
weekly  ███░░░░░░░  33%     6d6h
3 сброс(а) в запасе
```

Notifications look like:

```
✅ Codex — new window
gpt-5.6-luna · 12.0k tok · 6.9s
5h window until 21:45
```

> A token that another process is already long-polling cannot be shared: a
> Telegram bot has exactly one update stream. Use a dedicated bot for `poll = true`.
> Notifications (piece 1) work fine with any token.

## systemd

The unit is generated by the CLI itself, so a checkout and a pip-installed copy
produce the same file:

```sh
windowping service install      # write ~/.config/systemd/user/windowping.service, enable + start
windowping service status       # systemctl status + last log lines
windowping service logs -f      # journalctl -f
windowping service restart      # after editing the config
windowping service uninstall    # disable + remove the unit
```

`windowping service install --no-start` enables without starting, `--force`
rewrites a unit whose content drifted. `loginctl enable-linger "$USER"` keeps the
service alive when you are not logged in.

Prefer cron? Drop the daemon and run one pass every minute:

```cron
* * * * * /usr/bin/python3 -m windowping tick
```

## How the decision is made

For every provider, every tick:

1. weekly meter ≥ `weekly_threshold` → **skip**, notify once, wait for reset;
2. no active 5h window → **ping** now (unless a ping is still registering);
3. 5h window active, reset in the future → **wait**;
4. reset passed + `reset_buffer` → **ping**, once per reset timestamp;
5. anything else (cooldown, already pinged, provider dropped the 5h limit) → wait.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

109 unit tests cover window parsing for all four providers, the decision
algorithm, the watcher's notification/state behaviour, the systemd unit
renderer, the Telegram HTML formatting, the Codex API ping path (SSE
parsing, mode dispatch, CLI fallback), and the Claude provider (token reload
and refresh, usage cache, isolation flags, ping folder, transcript proof). The
interactive Claude ping runs against a fake `claude` on a real pty and is
skipped where there is none. No network needed.

## Adding a provider

A provider needs two things: free usage with a reset timestamp, and a cheap
request that starts the window. `docs/provider-research.md` records what the
survey of coding subscriptions found — which plans expose a readable per-user
usage endpoint, which bill monthly credits and therefore cannot be windowed, and
what a minimal ping looks like for each candidate (Claude Code, Kimi, MiniMax).

## License

MIT
