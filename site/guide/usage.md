# CLI Usage

The `windowping` CLI inspects usage meters, executes manual or dry-run pings, runs single scheduler passes or the continuous watcher, inspects stats, runs diagnostics, and manages the `systemd` user unit.

## Commands

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
windowping stats                  # what it did over the last 7 days
windowping stats --days 30        # ...over a month
windowping stats --json           # machine-readable
windowping stats --trim 120       # drop events older than 120 days
windowping config init|path|show
windowping service install|uninstall|status|logs
windowping service start|stop|restart|enable|disable
windowping doctor                 # read-only health check (--json for scripts)
```

## Command Aliases

- `status` → `s`
- `ping` → `p`
- `watch` → `w`
- `config` → `c`

## Config Path Overrides

By default `windowping` reads `~/.config/windowping/config.toml` (created with mode `600`). You can override the path with:

- `--config <path>` CLI flag
- `WINDOWPING_CONFIG` environment variable

## Selecting Multi-Account Instances

When [several accounts of one provider](/config/reference#several-accounts-of-one-provider) are configured (for example `codex:work` and `codex:personal`), the base provider name selects every enabled account, while `<provider>:<account>` selects one:

```sh
windowping status            # both accounts, on their own rows
windowping status codex      # both — the base name means "every account"
windowping status codex:work # just that one
windowping ping codex:work
```
