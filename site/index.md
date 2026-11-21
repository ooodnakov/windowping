---
layout: home

hero:
  name: windowping
  text: Keep 5-hour rate-limit windows back-to-back.
  tagline: Watches each provider's reset time and fires one tiny request right after rollover — pure Python 3.11+, stdlib only, zero dependencies.
  image:
    src: /logo.svg
    alt: windowping
  actions:
    - theme: brand
      text: Get Started
      link: /guide/what-it-does
    - theme: alt
      text: Providers
      link: /providers/overview
    - theme: alt
      text: GitHub
      link: https://github.com/ooodnakov/windowping

features:
  - title: Zero-Waste Rolling Windows
    details: Watches reset timestamps with configurable reset buffer, cooldown, registration grace, and a weekly meter guard so a reset is never pinged twice.
  - title: Six Coding-Plan Providers
    details: Supports Codex (CLI & 16-token API), Command Code, GLM Coding Plan, Claude Code (pty & opt-in API), plus opt-in Kimi for Coding and MiniMax Coding Plan.
  - title: Live Telegram Control Card
    details: One pinned message edited in place with Refresh, Ping, Stats, Schedule, New card, and Mute 8h buttons, plus quiet hours, EN/RU localization, and morning digests.
  - title: Pure Stdlib + systemd Watchdog
    details: Zero runtime dependencies on Python 3.11+. Ships a systemd user unit with Type=notify watchdog support, read-only doctor checks, and JSONL event stats.
---

## Quick Install

::: code-group

```sh [From PyPI]
pipx install windowping        # or: pip install --user windowping
windowping config init
windowping service install
```

```sh [From Git checkout]
git clone https://github.com/ooodnakov/windowping.git ~/Projects/windowping
cd ~/Projects/windowping
./install.sh                 # ~/.local/bin/windowping + systemd user unit
windowping config init       # write ~/.config/windowping/config.toml
$EDITOR ~/.config/windowping/config.toml
windowping status            # live meters
windowping ping --dry-run    # what a ping would send
```

```sh [No install (direct)]
PYTHONPATH=$PWD python3 -m windowping status
```

:::

```
✓ Codex: window opened (1.9s, 16 tokens)
gpt-5.6-luna · 5h window reset at Wed 19:52 MSK
```
