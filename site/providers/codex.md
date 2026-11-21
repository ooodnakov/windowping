# Codex Ping Modes

Two ways to start a Codex window, chosen with `[providers.codex] ping_mode`:

| Mode | What happens | Measured cost |
|---|---|---|
| `cli` (default) | `codex exec --ephemeral --json …` — the official CLI, which injects its whole agent prompt | ~12 000 input tokens per ping |
| `api` | one raw `POST /backend-api/codex/responses` with a one-message input, `max_output_tokens = 16` | **16 tokens** (11 in / 5 out), ~1.2 s |

## How `api` Mode Works

`api` speaks the same backend endpoint the CLI uses and authenticates with the same OAuth token, so it is billed against the subscription.

```toml
[providers.codex]
enabled = true
model = ""                   # "" = pick the cheapest model in the Codex catalog
effort = "low"
prompt = "ok"
ping_mode = "api"            # "cli" (~12k tokens) | "api" (~16 tokens)
ping_fallback = true         # retry through `codex exec` if the API path fails
```

It is an internal ChatGPT endpoint, not the documented public API: it can change without notice, and `ping_fallback = true` (the default) keeps window chaining alive by retrying through `codex exec` if the raw request fails. Measured on `codex-cli 0.163.0`.

::: info Minimum `max_output_tokens` and integer percentages
Requests below `max_output_tokens = 16` are rejected outright (`integer_below_min_value`), and the meter is an integer percentage, so a 16-token ping will not visibly move it.
:::

## OAuth Token Rotation

The Codex OAuth token is refreshed automatically through the same client the Codex CLI uses, and rotated tokens are written back to `~/.codex/auth.json`, so both `windowping` and the `codex` CLI stay in sync.
