# Stats & Morning Digest

Every ping, failure, weekly stop, and usage error is appended to `~/.local/state/windowping/events.jsonl` (one JSON object per line, next to the state file; override with `[general] history_file`). Nothing else is stored, and a lost line can never break a ping.

## CLI Stats

```sh
$ windowping stats --days 7
windowping stats — last 7d

windows opened   23   (~115h of coverage)
failed pings     1
tokens spent     1,240
time in pings    48.2s

by provider
  codex         12 window(s) · 192 tok · 22.0s
  commandcode    8 window(s) · 256 tok · 19.4s
  glm            3 window(s) · 792 tok · 6.8s · 1 failed
```

`≈ coverage` counts each successful ping as one 5-hour window, answering how much quota window time `windowping` kept alive.

Available flags:

- `windowping stats` — last 7 days
- `windowping stats --days 30` — custom day range
- `windowping stats --json` — machine-readable JSON output
- `windowping stats --trim 120` — prune events older than 120 days

## Telegram `/stats` and Morning Digest

The same numbers are available in the Telegram bot with `/stats` (`/stats 30` for a month) or the **📈 Stats** card button, and once a day as a quiet summary:

```toml
[telegram]
digest_at = "08:00"     # local time, "" = off
```

The digest is sent once per calendar day after the configured local time — after a restart, mid-day, whenever the watcher next runs. `digest` must be included in `notify_events` (it is by default).
