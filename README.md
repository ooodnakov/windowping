# windowping

Keep your **Codex**, **Command Code** and **GLM Coding Plan** 5-hour rate-limit
windows back-to-back.

All three providers run on rolling 5h windows (plus a weekly cap). A fresh 5h
window does **not** start when the previous one resets — it starts when you send
the first billable request. If that happens three hours later, those three hours
are wasted and your schedule drifts for the rest of the day.

`windowping` watches each provider's reset time and fires one tiny request
through the provider's own endpoint right after rollover, so the next window
starts immediately.

```
✓ Codex: окно открыто (6.9s, 11971 tokens)
gpt-5.6-luna · 5h window reset at Wed 19:52 MSK
```

Pure Python 3.11+, standard library only, no dependencies, no telemetry.

## What it does

| Job | Mechanism | Cost |
|-----|-----------|------|
| Read usage & reset time | each provider's own usage endpoint (zero quota) | free, never starts a window |
| Start the next window | one minimal billable request (`max_tokens=1`, or `codex exec --ephemeral`) | a sliver of quota — the whole point |

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
| **Codex** | `GET chatgpt.com/backend-api/wham/usage` | `codex exec --ephemeral --json` | OAuth in `~/.codex/auth.json` |
| **Command Code** | `GET api.commandcode.ai/alpha/billing/credits` | `POST …/provider/v1/chat/completions` | API key in `~/.commandcode/auth.json` |
| **GLM Coding Plan** | `GET api.z.ai/api/monitor/usage/quota/limit` | `POST api.z.ai/api/coding/paas/v4/chat/completions` | `GLM_API_KEY` |

The Codex OAuth token is refreshed automatically through the same client the
Codex CLI uses, and rotated tokens are written back to `~/.codex/auth.json`, so
both tools stay in sync.

> **GLM note:** only coding-plan tiers count. Legacy models such as
> `glm-4.5-flash` answer `200 OK` but never touch the plan's quota, so they never
> start a window. Keep `model` on a coding tier (`glm-5.3-flash` by default).

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
workdir = "~"                # cwd for the codex exec ping

[providers.codex]
enabled = true
model = ""                   # "" = cheapest model in the Codex catalog
effort = "low"
prompt = "ok"

[providers.commandcode]
enabled = true
model = "deepseek/deepseek-v4.1-flash"
prompt = "ok"

[providers.glm]
enabled = true
model = "glm-5.3-flash"
prompt = "ok"
api_key_env = "GLM_API_KEY"  # falls back to api_key = "..."

[telegram]
enabled = false
bot_token = ""               # or bot_token_env = "WINDOWPING_BOT_TOKEN"
chat_id = 0
notify_events = ["ping", "error", "weekly"]
poll = false                 # answer /status and /ping in the bot
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
   to `allow_chat_ids` (defaults to `chat_id`).

> A token that another process is already long-polling cannot be shared: a
> Telegram bot has exactly one update stream. Use a dedicated bot for `poll = true`.
> Notifications (piece 1) work fine with any token.

## systemd

`install.sh` writes `~/.config/systemd/user/windowping.service` and enables it.
Manual equivalent:

```sh
mkdir -p ~/.config/systemd/user
sed "s|@REPO@|$PWD|g" systemd/windowping.service > ~/.config/systemd/user/windowping.service
systemctl --user daemon-reload
systemctl --user enable --now windowping.service
journalctl --user -u windowping.service -f
```

`loginctl enable-linger "$USER"` keeps it alive when you are not logged in.

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

29 unit tests cover window parsing for all three providers, the decision
algorithm, and the watcher's notification/state behaviour. No network needed.

## License

MIT
