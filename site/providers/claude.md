# Claude Code & API Ping

Claude Code (Pro / Max) is opt-in: set `[providers.claude] enabled = true`.

Ported from [wavever/CCLimitPing](https://github.com/wavever/CCLimitPing) (MIT).

## Default Mode: Interactive CLI (`ping_mode = "cli"`)

- **Usage** is a read-only `GET /api/oauth/usage` with the Claude Code login (the macOS Keychain item `Claude Code-credentials`, else `~/.claude/.credentials.json`; `$CLAUDE_CONFIG_DIR` is honoured). On a `401` the store is re-read first, since the CLI may have refreshed it, and only then is the token refreshed through Claude Code's own OAuth client and written back. The endpoint throttles hard, so a read is reused for `read_interval` (default `5m`) unless one of its resets has passed, and a `429` falls back to that read.
- **Ping** is one *interactive* `claude --model haiku -- ok` turn on a pseudo-terminal. Print mode (`claude -p`) is billed to Agent SDK / API credits, not the subscription, so it never starts a window. The session runs under its own `--session-id`, with hooks and prompt suggestions off (`--settings`), no MCP servers (`--strict-mcp-config`), no tools (`--tools ""`), no `CLAUDE.md` and no prompt-history entry, each flag only when the installed CLI lists it. Its transcript is read to prove that a real reply came back (model and tokens, or Claude Code's own error), then deleted, so pings never pile up in `claude --resume`.
- **Folder:** Claude Code asks whether to trust an unknown folder, and a ping cannot answer. So it runs in `workdir` only when Claude Code trusts it, and otherwise borrows a trusted folder that has no `.claude/settings*.json`. Pin one with `ping_dir`.
- **Platform:** The interactive CLI ping needs a POSIX pty (Linux / macOS); `windowping status` works everywhere.

## Opt-in API Mode (`ping_mode = "api"`)

`ping_mode = "api"` skips the pty and posts one message instead:

```http
POST https://api.anthropic.com/v1/messages
Authorization: Bearer <oauth token>      anthropic-beta: oauth-2025-04-20
anthropic-version: 2023-06-01            User-Agent: claude-code/<version>

{"model": "claude-haiku-4-5", "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]}
```

This is the shape of Claude Code's own startup prefetch — a single turn, a single output token, a fraction of a cent. The response carries `anthropic-ratelimit-unified-5h-{utilization,reset}`, so one ping also returns the fresh meter reading and the new reset time.

::: warning Unverified against a live subscription
Whether a raw `/v1/messages` call on the subscription OAuth token anchors a new 5h window has not been measured on a live account. The default stays `cli` for that reason; with `ping_fallback = true` a failing API ping retries through the CLI, so windows keep chaining either way. If you want to test it: set `ping_mode = "api"`, wait for a reset, and compare `five_hour.resets_at` in `windowping status` before and after.
:::

::: info OAuth Token Terms Heads-up
`/api/oauth/usage` is an internal endpoint, not a public API, and Anthropic's terms reserve subscription OAuth tokens for Claude Code and Claude.ai. `windowping` uses the token only to read the meter (and refresh it on a 401); the default billable ping goes through the official CLI. The opt-in `ping_mode = "api"` is the one place a raw request is sent with that token — decide for yourself whether that is acceptable for your account.
:::
