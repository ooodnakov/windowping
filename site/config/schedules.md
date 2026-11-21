# Per-Provider Schedules

Not every plan is used every day, and a 5-hour window opened at the wrong time is a wasted ping. Each provider (or account) can carry its own `schedule`:

```toml
[providers.glm]
schedule = "mon-fri"                # no weekend pings
# schedule = "mon-fri 07:00-23:30"  # weekdays, working hours only
# schedule = "weekends 10:00-02:00" # wraps midnight
# schedule = "never"                # keep reading usage, never ping
```

## Supported Schedule Forms

| Example | Meaning |
|---|---|
| `"always"` | Ping on any reset (default) |
| `"never"` | Keep reading usage, never ping |
| `"mon-fri"` | Weekdays only |
| `"mon-fri 07:00-23:30"` | Weekdays during local daytime hours |
| `"weekends 10:00-02:00"` | Weekends, wrapping past midnight into the next day |

## Behavior & Validation

- **Fail-fast validation:** A malformed `schedule` spec fails immediately at config load / startup, not at 3am.
- **Gates pings only:** Usage is still read outside the active schedule, so `/status`, the live card, and the weekly meter stay current, and a metered read costs nothing.
- **Bot inspection:** Check schedules from Telegram with `/schedule` (or `/расписание`) — it prints each provider's configured window and the next moment it opens.
