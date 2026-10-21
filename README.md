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
   to `allow_chat_ids` (defaults to `chat_id`). Bare words work too: `status`,
   `ping`.

Replies are Telegram HTML: provider names in bold, meters in a monospace
`<pre>` block, status icons per provider (🟢 ok, 🟠 weekly exhausted, 🔴 error,
⚪️ no data). If Telegram rejects an entity, the message is re-sent as plain text
instead of being dropped:

```
🟢 codex · plus
5h      █████████░  92%    2h44m
weekly  ███░░░░░░░  33%     6d6h
3 сброс(а) в запасе
```

Notifications look like:

```
✅ Codex — новое окно
gpt-5.6-luna · 12.0k tok · 6.9s
5h-окно до 21:45
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

48 unit tests cover window parsing for all three providers, the decision
algorithm, the watcher's notification/state behaviour, the systemd unit
renderer, and the Telegram HTML formatting. No network needed.

## Releasing to PyPI

The name `windowping` is free on PyPI. One-time setup:

1. Create an account on <https://pypi.org> and enable 2FA.
2. Create an API token (Account settings → API tokens) scoped to the project
   once it exists, or to "entire account" for the first upload.
3. Store it outside the repo, e.g. `~/.pypirc` with mode 600:

   ```ini
   [pypi]
   username = __token__
   password = pypi-AgEIcHlwaS5vcmc…
   ```

Then each release:

```sh
python3 -m pip install --user build twine
python3 -m build                    # dist/windowping-0.1.0-py3-none-any.whl + .tar.gz
python3 -m twine check dist/*
python3 -m twine upload dist/*
```

Bump `version` in `pyproject.toml` before every upload — PyPI rejects a version
it has already seen. Test the upload against TestPyPI first with
`--repository testpypi` after adding that section to `~/.pypirc`.

**Trusted publishing (no tokens):** on PyPI → Publishing, add a GitHub Actions
publisher for `ooodnakov/windowping` with workflow `publish.yml` and environment
`pypi`; the workflow then uploads via OIDC on every `v*` tag. That needs the
repository to be public for other people, but a private repo can still publish.

## License

MIT
