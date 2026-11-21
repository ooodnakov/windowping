# Adding a Provider & Tests

## Running Tests

```sh
python3 -m unittest discover -s tests -v
```

No network is needed. Unit tests cover:

- window parsing across all supported providers (`codex`, `commandcode`, `glm`, `claude`, `kimi`, `minimax`);
- multi-account instance resolution and config validation;
- per-provider schedule parsing and quiet hours;
- the decision engine and watcher notification/state behavior;
- reliability behavior (retries, error classification, usage caching, `reset_seen`);
- the `systemd` unit renderer and CLI service helpers;
- Telegram HTML formatting, i18n (`en`/`ru`), polling resilience, and live card rendering/callbacks;
- the Codex API ping path (SSE parsing, mode dispatch, CLI fallback);
- the Claude provider (token reload and refresh, usage cache, isolation flags, ping folder, transcript proof);
- `windowping doctor` checks.

The interactive Claude ping test runs against a fake `claude` on a real pseudo-terminal and is skipped where there is no POSIX pty (e.g. non-POSIX platforms).

## Adding a Provider

A provider needs two things:

1. **Free usage read** returning usage percentages and a reset timestamp without consuming quota.
2. **Cheap billable request** that starts or anchors a new 5-hour window.

Check [Provider Research](/providers/research) for notes on which coding subscriptions expose a readable per-user usage endpoint, which bill monthly credits and cannot be windowed, and what minimal pings look like for each candidate.

## License

MIT
