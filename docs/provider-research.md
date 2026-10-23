# Provider research

Notes from a survey (October 2026) of how coding subscriptions expose rate-limit
usage and how a 5-hour window can be started with a minimal request. The goal is
to keep `windowping` extensible without guesswork: every claim below carries the
evidence level it was obtained with.

Legend: **VERIFIED** — read in published source, live docs, or observed on a real
account. **INFERRED** — deduced from a working third-party client or docs wording.

## Implemented

| Provider | Usage (free) | Ping (billable) | Status |
|---|---|---|---|
| `codex` | `GET https://chatgpt.com/backend-api/wham/usage` | `POST …/backend-api/codex/responses`, `max_output_tokens: 16` (~16 tokens measured) or `codex exec` in `cli` mode | production |
| `commandcode` | `GET https://api.commandcode.ai/alpha/billing/credits` | `POST …/provider/v1/chat/completions`, `max_tokens: 1` | production |
| `glm` | `GET https://api.z.ai/api/monitor/usage/quota/limit` (`unit` 3 = 5h, 6 = weekly) | `POST …/coding/paas/v4/chat/completions`, `glm-5.3-flash` | production |
| `claude` | `GET https://api.anthropic.com/api/oauth/usage` | interactive `claude` turn on a pty, or opt-in 1-token `/v1/messages` | production, opt-in |
| `kimi` | `GET https://api.kimi.com/coding/v1/usages` | `POST https://api.kimi.com/coding/v1/chat/completions`, `max_tokens: 1` | usage **VERIFIED**, ping **INFERRED**, disabled by default |
| `minimax` | `GET https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains` | `POST https://api.minimax.io/v1/text/chatcompletion_v2`, `max_tokens: 1` | usage **VERIFIED**, ping **INFERRED**, disabled by default |

## Implemented details

### Claude Code (Pro / Max)

All of the following is **VERIFIED** by reading the minified `cli.js` of
`@anthropic-ai/claude-code@2.1.112` and the string table of the 2.1.306 native
binary — not by calling the API.

Usage, no quota spent:

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <accessToken from ~/.claude/.credentials.json>
anthropic-beta: oauth-2025-04-20
User-Agent: claude-code/<version>
timeout: 5s
```

No `anthropic-version` header. Gated on an OAuth token carrying the `user:inference`
and `user:profile` scopes. Response carries `five_hour`, `seven_day`,
`seven_day_sonnet` and `extra_usage`; each limit is `{utilization, resets_at}`
where `utilization` is a percentage 0–100 and `resets_at` is an **ISO-8601
string** (the rate-limit headers use epoch seconds — do not mix the two).

Ping: Anthropic's own CLI already does exactly this as a startup prefetch —
`messages.create({model, max_tokens: 1, messages: [{role: "user", content: "quota"}]})`
with `anthropic-beta: oauth-2025-04-20`; the 5h window constant is
`windowSeconds: 18000`. Every `/v1/messages` response also ships
`anthropic-ratelimit-unified-5h-{utilization,reset}` headers, so a ping doubles as
a fresh measurement.

Print mode does not work: `claude -p` is billed to Agent SDK / API credits and
never starts a subscription window. The ping that does work is one *interactive*
`claude` turn on a pseudo-terminal — see the `claude` provider in
`windowping/providers/claude.py` and the "Claude ping" section of the README,
which also covers folder-trust handling and the read-only use of the token.

### Kimi for Coding — implemented as `providers/kimi.py`

**VERIFIED** via a working third-party client
([`kimi-code-usage`](https://github.com/Golden0Voyager/kimi-code-usage)):

```
GET https://api.kimi.com/coding/v1/usages
Authorization: Bearer sk-kimi-…   (or the Kimi CLI OAuth token)
→ data.usages[].window{duration, timeUnit}, used, limit, resetTime
```

Windows: 5h, weekly and monthly are all reported, and the window length is in the
payload rather than hardcoded — which is why the provider picks the 5h window by
`duration × timeUnit`, not by list position. Ping: single-token chat on the
OpenAI-compatible `https://api.kimi.com/coding/v1`. The *ping* half is **INFERRED**
from that surface and is unverified on a live plan; the provider therefore ships
`enabled = false` with a configurable `model`.

### MiniMax coding plan — implemented as `providers/minimax.py`

**VERIFIED** via a working third-party client
([`minimax-status`](https://github.com/JochenYang/minimax-status)):

```
GET https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains
Authorization: Bearer <plan key>
→ model_remains[]: {start_time, end_time, remains_time,
                    current_interval_total_count, current_interval_usage_count}
```

Caveat: the interval in the sample payload is a fixed block (10:00–15:00), i.e.
aligned 5h buckets rather than a rolling window anchored on first use. The
provider therefore classifies a block by `end_time - start_time` (≤ 7.5h → the 5h
window, ≥ 6 days → weekly) and takes the reset from `end_time`. The *ping* is
**INFERRED** from the OpenAI-compatible surface and unverified on a live plan;
`base_url`, `ping_path` and `model` are all configurable because the China and
international deployments differ.

## Rejected

| Plan | Why not |
|---|---|
| GitHub Copilot Pro / Pro+ | Premium-request billing is legacy-only for annual plans since Jun 2026; the metrics REST API is `/orgs/{org}` or `/enterprises/{ent}` only, so a personal subscription has no readable counter. |
| Cursor Pro | Monthly included usage plus on-demand, reset on the billing-cycle day — not a 5h window. Only the Admin API for teams, or IDE local state / dashboard cookies. |
| Windsurf | Monthly prompt credits, no rollover; self-serve plans moved to usage-based (Devin) in Mar 2026. UI-only visibility. |
| Zed AI | $10/mo = $5 of token credits per month, usage-based after. Account page only. |
| JetBrains AI | Monthly credit pool, IDE panel only. |
| Qwen / Alibaba coding plan | The 5h/weekly/monthly windows exist, but no documented per-user usage endpoint — known tools fall back to a local estimate. |
| Cerebras, Groq, OpenRouter free | Rate limits are RPM/TPM style, not a fillable window. OpenRouter does expose `/api/v1/key`, but there is nothing to keep chained. |

## Offline signals (no API call)

- **Codex rollouts** — `~/.codex/sessions/**/*.jsonl` record
  `"rate_limits": {"primary": {"used_percent": …, "window_minutes": 300, "resets_at": …}}`
  (`300` = 5h, `10080` = weekly). Server truth on disk, but only written by the
  CLI, so it is useless as evidence for an API ping.
- **Claude statusline** — the `rate_limits` block in the statusline JSON exposes
  `five_hour` / `seven_day` `used_percentage` and `resets_at`, and is documented
  as "only present for subscribers after the first API response".
- **Claude limit marker** — Claude Code logs a synthetic error line
  `Claude AI usage limit reached|<unix_s>` (`isApiErrorMessage: true`) that
  carries the exact reset epoch.

## Lessons from existing trackers

`ccusage` (Rust, MIT, ~25 adapters) parses local logs and goes online only for
pricing. Its 5h block algorithm — `start = floor_to_hour(first_entry.ts)`,
`end = start + 5h`, new block when `since_start > 5h` or the gap exceeds 5h — is
a client-side approximation that can be off by up to 59 minutes, and a quiet but
open window reads as closed. Useful as a cross-check, **not** as the trigger for
a ping: prefer server-provided reset epochs everywhere.

No tracker in the survey pings to open a window; `unsnooze` merely resumes a
stopped session. Window chaining appears to be unexplored territory.
