# What It Does

All supported coding-plan providers run on rolling 5-hour windows (plus a weekly cap, or aligned blocks for MiniMax). A fresh 5h window does **not** start when the previous one resets — it starts when you send the first billable request. If that happens three hours later, those three hours are wasted and your schedule drifts for the rest of the day.

`windowping` watches each provider's reset time and fires one tiny request through the provider's own endpoint right after rollover, so the next window starts immediately.

```
✓ Codex: window opened (1.9s, 16 tokens)
gpt-5.6-luna · 5h window reset at Wed 19:52 MSK
```

Pure Python 3.11+, standard library only, no dependencies, no telemetry.

## Mechanism & Cost

| Job | Mechanism | Cost |
|---|---|---|
| Read usage & reset time | each provider's own usage endpoint (zero quota) | free, never starts a window |
| Start the next window | one minimal billable request (`max_tokens=1`, `codex exec --ephemeral`, or one interactive Claude Code turn) | a sliver of quota — the whole point |

## Safety Rails

All safety rails are configurable in `[general]` of [`config.toml`](/config/reference):

- **weekly guard** — stop pinging once the weekly meter is at/above `weekly_threshold` (default `0.99`, i.e. 99%): more pings cannot help until it resets;
- **reset buffer** — wait `reset_buffer` (default `5m`) past the reset before pinging, so a clock skew cannot land the request in the old window;
- **cooldown** — never re-ping the same provider within `cooldown` (default `10m`);
- **register grace** — if a ping has not shown up in the usage meter yet, wait up to `register_grace` (default `30m`) instead of pinging again;
- **once per window** — a reset that was already pinged is never pinged twice, even across restarts (`state.json`).

## Next Steps

- [Install windowping](/guide/install)
- [Supported providers](/providers/overview)
- [Configuration reference](/config/reference)
- [How the decision engine works](/reference/decision-engine)
