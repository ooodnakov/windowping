# Doctor & Diagnostics

When nothing happens, `windowping doctor` says which part is broken — without reading code. It is read-only and exits non-zero only on real failures (pass `--json` for scripts):

```sh
$ windowping doctor
windowping doctor — 0.2.1

✓ python                3.14.7
✓ config                /home/rem/.config/windowping/config.toml (mode 0o600)
✓ state dir             /home/rem/.local/state/windowping
✓ event log             /home/rem/.local/state/windowping/events.jsonl (8 events in 7d)
✓ clock                 +0.2s vs Telegram
✓ provider codex        5h 38% · resets in 1h59m · weekly 36% · plus
✗ provider glm          HTTP 401: invalid api key
                        → credentials were rejected: log in again or replace the key
✓ codex cli             not needed (ping_mode = api)
✓ telegram              @windowping_bot
✓ telegram chat         chat_id 298465764
✓ quiet hours           12:00-08:00 (silent deliveries)
✓ service               active, enabled
✓ watcher               last tick 0m18s ago

14 ok, 1 failed
```

## What `doctor` Checks

- Python version (`3.11+`)
- Config path and permissions (world-readable secrets produce a warning)
- State directory writability
- Event log (`events.jsonl`)
- Clock skew against a real HTTP `Date` header
- Every enabled provider's usage endpoint
- CLI binaries a provider needs for its `ping_mode`
- Telegram bot token via `getMe` and target `chat_id`
- `quiet_hours` and `digest_at` syntax
- `systemd` user unit status (`active`, `enabled`)
- Whether the watcher ticked recently
