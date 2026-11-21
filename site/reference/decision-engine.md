# Decision Engine

For every enabled provider (or account instance), on every watcher tick:

1. **Weekly meter ≥ `weekly_threshold`** → **skip**, notify once, wait for reset;
2. **No active 5h window** → **ping** now (unless a recent ping is still registering within `register_grace`, or the provider is outside its configured [`schedule`](/config/schedules));
3. **5h window active, reset in the future** → **wait**;
4. **Reset passed + `reset_buffer`** → **ping**, once per reset timestamp (`state.json` records pinged reset timestamps across restarts);
5. **Anything else** (`cooldown`, `failed_ping_cooldown`, already pinged, provider dropped the 5h limit) → **wait**.

## Usage Read Caching & Retries

- Usage meters are read on `usage_interval` (default `30m`) rather than on every `60s` tick.
- A window reset, a failed ping, or pressing **Refresh** on the Telegram card forces an immediate read; the tick loop still runs every `60s` so pings land promptly after rollover.
- A confirmed reset is remembered (`reset_seen`), so a provider that cannot be pinged (outside `schedule`, exhausted weekly quota) does not trigger a read on every tick.
- A cached reading survives a broken read (`network` or transient failure), keeping the card numbers intact instead of flipping the provider into an error state.
- Connection-level failures (`network`) are retried within the tick (`ping_retries`, `read_retries`) with doubling delay (`retry_delay`); HTTP/payload errors (`provider`) are never retried inside the same tick and wait `failed_ping_cooldown`.
