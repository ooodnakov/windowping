# Telegram & Live Card

Telegram support consists of two independent pieces, both optional:

1. **Notifications** — one message per transition: window opened, ping failed, weekly cap exhausted, connection recovered. Only transitions are sent, so a healthy day is silent. `bot_token` + `chat_id` is enough; `poll` can stay off.
2. **Commands** — with `poll = true`, the watcher also long-polls `getUpdates` and answers `/status`, `/ping`, `/ping glm`, `/stats`, `/schedule`, `/card`, and `/help`. Replies are restricted to `allow_chat_ids` (defaults to `chat_id`). Bare words work too: `status`, `ping`.

::: warning Dedicated bot token for `poll = true`
A token that another process is already long-polling cannot be shared: a Telegram bot has exactly one update stream. Use a dedicated bot when `poll = true`. Notifications (piece 1) work fine with any token.
:::

## One Live Card, A Few Buttons

When `[general] card = true` (default), the bot keeps **one pinned message** that it edits in place instead of spamming a stream of status messages:

```
📊 limits

🟢 Codex · plus
5h     █░░░░░░░░░  14%    2h03m
weekly ██░░░░░░░░  18%        —

🟠 Command Code
5h     ░░░░░░░░░░   0%        —
weekly ██████████ 100%   23h27m

🟢 GLM · lite
5h     █░░░░░░░░░   1%    1h08m
weekly ███░░░░░░░  32%    2d20h

updated 20:31 · next auto at 21:01
[🔄 Refresh] [⏱ Ping]
[📈 Stats]  [🗓 Schedule]
[🆕 New card] [🔇 Mute 8h]
```

- **Refresh** reads usage right now (the automatic cadence is every 30 minutes, `usage_interval`), then edits the card in place.
- **Ping** runs one tick: everything the watcher would do on its own schedule.
- **Stats / Schedule** answer in a separate message.
- **🆕 New card** (or `/card`, `/карточка`) deletes the old message and posts a fresh one at the bottom — edits keep a message where it was, and after a long day that is above the fold. Every new card is pinned, so it also stays on top.
- **Mute 8h** silences routine messages for `mute_hours` (default `8`); an escalation still gets through, because that is the one message worth waking up for.

The card only repaints when something actually changed — a new reading, a new decision, or a button — so it does not spend an edit per minute.

Pings that happen in the same tick are reported as **one** message, and network failures are counted per incident rather than per provider (`network_notify_cooldown = "30m"`).

## Language Detection (`lang`)

The bot speaks **English and Russian**. `[telegram] lang = "auto"` (default) follows the sender's Telegram `language_code`, so the same deployment answers a Russian client in Russian and an English one in English; `"en"` or `"ru"` pins everything. Notifications follow the owner's last seen language. The rest of the project — CLI output, docs, code — is English only.

## Quiet Hours

Telegram has no server-side schedule, but every message can be sent with `disable_notification` — delivered, just silent. Set the ranges in local time and the bot stops buzzing inside them (replies included):

```toml
[telegram]
quiet_hours = "12:00-08:00"          # wraps midnight
# quiet_hours = "23:00-07:00,13:00-14:00"   # several ranges
```

A malformed spec fails at startup instead of silently leaving the phone loud. `silent = true` still forces silence around the clock.

## Formatting & Notifications

Replies use Telegram HTML: provider names in bold, meters in a monospace `<pre>` block, status icons per provider (`🟢` ok, `🟠` weekly exhausted, `🔴` error, `⚪️` no data). If Telegram rejects an entity, the message is re-sent as plain text instead of being dropped:

```
🟢 codex · plus
5h      █████████░  92%    2h44m
weekly  ███░░░░░░░  33%     6d6h
3 reset credit(s) available
```

Russian client output:

```
🟢 codex · plus
5h      █████████░  92%    2h44m
weekly  ███░░░░░░░  33%     6d6h
3 сброс(а) в запасе
```

Transition notifications look like:

```
✅ Codex — new window
gpt-5.6-luna · 12.0k tok · 6.9s
5h window until 21:45
```
