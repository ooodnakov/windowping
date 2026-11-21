# Supported Providers

| Provider | Usage (free) | Ping (billable) | Auth |
|---|---|---|---|
| **Codex** | `GET chatgpt.com/backend-api/wham/usage` | `POST …/backend-api/codex/responses` (`api` mode, ~16 tokens) or `codex exec --ephemeral --json` (`cli` mode) | OAuth in `~/.codex/auth.json` |
| **Command Code** | `GET api.commandcode.ai/alpha/billing/credits` | `POST …/provider/v1/chat/completions` | API key in `~/.commandcode/auth.json` |
| **GLM Coding Plan** | `GET api.z.ai/api/monitor/usage/quota/limit` | `POST api.z.ai/api/coding/paas/v4/chat/completions` | `GLM_API_KEY` |
| **Claude Code** | `GET api.anthropic.com/api/oauth/usage` | one interactive `claude` turn on a pty (see [Claude Code & API Ping](/providers/claude)) | Claude Code login (Keychain / `~/.claude/.credentials.json`) |
| **Kimi for Coding** | `GET api.kimi.com/coding/v1/usages` (window length comes from the payload) | `POST api.kimi.com/coding/v1/chat/completions`, `max_tokens: 1` | `KIMI_API_KEY` |
| **MiniMax Coding Plan** | `GET minimaxi.com/v1/api/openplatform/coding_plan/remains` (aligned blocks) | `POST api.minimax.io/v1/text/chatcompletion_v2`, `max_tokens: 1` | `MINIMAX_API_KEY` |

## Provider Notes

### Codex OAuth Sync

The Codex OAuth token is refreshed automatically through the same client the Codex CLI uses, and rotated tokens are written back to `~/.codex/auth.json`, so both tools stay in sync. See [Codex Ping Modes](/providers/codex) for details on `cli` vs `api` ping modes.

### GLM Coding Plan

::: warning Coding-plan tiers only
Only coding-plan tiers count. Legacy models such as `glm-4.5-flash` answer `200 OK` but never touch the plan's quota, so they never start a window. Keep `model` on a coding tier (`glm-5.3-flash` by default).
:::

### Kimi for Coding & MiniMax Coding Plan

::: info Opt-in & inferred ping endpoints
Both `kimi` and `minimax` ship with `enabled = false` by default. Their usage envelopes were lifted from working third-party clients (`kimi-code-usage`, `minimax-status`), but the **ping** endpoints have not been exercised on a live plan — that needs a real key.

- Model names on those surfaces track the plan, so set `model` before enabling them.
- For MiniMax, set `base_url` / `ping_path` if you are on the China deployment (`https://api.minimaxi.com/v1`).
- MiniMax bills in **aligned blocks** rather than a rolling window, so its reset comes from the block's `end_time`, never "reset + 5h".
:::

### Claude Code

Claude Code (Pro / Max) is opt-in (`[providers.claude] enabled = true`). See [Claude Code & API Ping](/providers/claude).
