"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .bot import BotCommands
from .config import DEFAULT_CONFIG_PATH, load, write_default_config
from .notify import TelegramNotifier, TelegramPoller, send_message
from .providers import build_one, build_providers
from .render import message_test, status_text, usage_lines
from . import service as service_mod
from .watcher import Watcher


def _providers(config, names: list[str]):
    if not names:
        return build_providers(config)
    selected = []
    for name in names:
        provider = build_one(config, name)
        if provider is None:
            raise SystemExit(f"unknown provider: {name} (have: {', '.join(config.providers) or 'none'})")
        selected.append(provider)
    return selected


def cmd_status(args) -> int:
    config = load(args.config)
    providers = _providers(config, args.providers)
    now = time.time()
    payload = []
    rows = []
    for provider in providers:
        try:
            usage = provider.usage()
            rows.append((provider.name, usage, None))
            payload.append(
                {
                    "provider": provider.name,
                    "plan": usage.plan,
                    "five_hour": {
                        "used_percent": usage.five.pct,
                        "resets_at": usage.five.reset_at,
                        "enforced": usage.five.enforced,
                    },
                    "weekly": {
                        "used_percent": usage.weekly.pct,
                        "resets_at": usage.weekly.reset_at,
                        "enforced": usage.weekly.enforced,
                    },
                    "details": usage.details,
                }
            )
        except Exception as exc:  # noqa: BLE001 - report per provider
            rows.append((provider.name, None, str(exc)))
            payload.append({"provider": provider.name, "error": str(exc)})
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        if rows:
            print(status_text(rows, now))
        else:
            print("no providers enabled")
    return 0 if all(row[2] is None for row in rows) else 1


def cmd_ping(args) -> int:
    config = load(args.config)
    providers = _providers(config, args.providers)
    if not providers:
        print("no providers enabled")
        return 0
    watcher = Watcher(config)
    rc = 0
    for provider in providers:
        if args.dry_run:
            print(f"{provider.name:<12} would ping")
            continue
        try:
            usage = provider.usage()
        except Exception:  # noqa: BLE001 - still ping, state unknown
            usage = None
        result = provider.ping()
        if result.ok:
            bits = []
            if result.seconds:
                bits.append(f"{result.seconds:.1f}s")
            if result.tokens:
                bits.append(f"{result.tokens} tokens")
            suffix = f" ({', '.join(bits)})" if bits else ""
            print(f"{provider.name:<12} ✓ pinged{suffix} {result.model or ''}".rstrip())
            watcher.state.update(
                provider.name,
                last_ping=time.time(),
                pinged_for_reset=(usage.five.reset_at if usage else None),
            )
        else:
            print(f"{provider.name:<12} ✗ {result.error}")
            rc = 1
    watcher.state.save()
    return rc


def cmd_tick(args) -> int:
    config = load(args.config)
    providers = _providers(config, args.providers)
    notifier = TelegramNotifier(config.telegram)
    watcher = Watcher(config, notifier)
    results = watcher.tick(providers, dry_run=args.dry_run)
    stamp = time.strftime("%H:%M:%S")
    rc = 0
    for result in results:
        if result.error:
            print(f"{stamp} [{result.provider}] error: {result.error}")
            rc = 1
            continue
        decision = result.decision
        if decision is None:
            continue
        print(f"{stamp} [{result.provider}] {decision.action}: {decision.reason}")
        if result.ping and not result.ping.ok:
            rc = 1
    return rc


def cmd_watch(args) -> int:
    config = load(args.config)
    providers = _providers(config, args.providers)
    if not providers:
        print("no providers enabled", file=sys.stderr)
        return 2
    notifier = TelegramNotifier(config.telegram)
    watcher = Watcher(config, notifier)

    stop = threading.Event()
    if notifier.active and config.telegram.poll and not args.no_bot:
        commands = BotCommands(config)
        poller = TelegramPoller(config.telegram, commands.handle)
        thread = threading.Thread(
            target=poller.poll_forever, kwargs={"stop_event": stop}, daemon=True, name="telegram-bot"
        )
        thread.start()
        watcher.log("telegram bot polling enabled")

    watcher.run_forever(providers, stop)
    return 0


def cmd_bot(args) -> int:
    config = load(args.config)
    notifier = TelegramNotifier(config.telegram)
    if not notifier.active:
        print(
            "telegram is not configured (set [telegram] enabled, bot_token/bot_token_env and chat_id)",
            file=sys.stderr,
        )
        return 2
    commands = BotCommands(config)
    poller = TelegramPoller(config.telegram, commands.handle)
    print("polling telegram updates (Ctrl-C to stop)", flush=True)
    try:
        poller.poll_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def cmd_notify_test(args) -> int:
    config = load(args.config)
    notifier = TelegramNotifier(config.telegram)
    if not notifier.active:
        print(
            "telegram is not active: need [telegram] enabled=true, a bot token and chat_id",
            file=sys.stderr,
        )
        return 2
    chat_id = config.telegram.chat_id
    if chat_id is None:
        print("telegram chat_id is not set", file=sys.stderr)
        return 2
    text = args.text or message_test(str(config.path), list(config.providers))
    try:
        send_message(notifier.token, int(chat_id), text, silent=False)
    except Exception as exc:  # noqa: BLE001 - CLI feedback
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    print("sent")
    return 0


def cmd_service(args) -> int:
    return service_mod.run(
        args.action,
        start=not args.no_start,
        force=args.force,
        follow=args.follow,
        lines=args.lines,
    )


def cmd_config(args) -> int:
    path = Path(args.config or DEFAULT_CONFIG_PATH).expanduser()
    action = args.action or "path"
    if action == "init":
        written = write_default_config(path, overwrite=args.force)
        print(written)
        return 0
    if action == "path":
        print(path)
        return 0
    if action == "show":
        print(path.read_text(encoding="utf-8") if path.exists() else f"missing: {path}")
        return 0
    raise SystemExit(f"unknown config action: {action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="windowping",
        description="Keep Codex, Command Code and GLM 5h rate-limit windows back-to-back.",
    )
    parser.add_argument("--config", help="path to config.toml (default ~/.config/windowping/config.toml)")
    parser.add_argument("--version", action="version", version=f"windowping {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", aliases=["s"], help="show 5h/weekly meters")
    status.add_argument("providers", nargs="*", help="limit to these providers")
    status.add_argument("--json", action="store_true", help="machine-readable output")
    status.set_defaults(func=cmd_status)

    ping = subparsers.add_parser("ping", aliases=["p"], help="ping now")
    ping.add_argument("providers", nargs="*")
    ping.add_argument("--dry-run", action="store_true", help="show what would be pinged")
    ping.set_defaults(func=cmd_ping)

    tick = subparsers.add_parser("tick", help="one scheduler pass (cron friendly)")
    tick.add_argument("providers", nargs="*")
    tick.add_argument("--dry-run", action="store_true")
    tick.set_defaults(func=cmd_tick)

    watch = subparsers.add_parser("watch", aliases=["w"], help="run the watcher in the foreground")
    watch.add_argument("providers", nargs="*")
    watch.add_argument("--no-bot", action="store_true", help="do not start the telegram bot thread")
    watch.set_defaults(func=cmd_watch)

    bot = subparsers.add_parser("bot", help="run only the telegram command bot")
    bot.set_defaults(func=cmd_bot)

    notify_test = subparsers.add_parser("notify-test", help="send one telegram test message")
    notify_test.add_argument("text", nargs="?", help="custom message body")
    notify_test.set_defaults(func=cmd_notify_test)

    service = subparsers.add_parser(
        "service", aliases=["svc"], help="manage the systemd user unit"
    )
    service.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=list(service_mod.ACTIONS),
        help="install/uninstall the unit, or control the running service",
    )
    service.add_argument("--no-start", action="store_true", help="install: enable without starting")
    service.add_argument("--force", action="store_true", help="install: rewrite a differing unit")
    service.add_argument("-f", "--follow", action="store_true", help="logs: follow the journal")
    service.add_argument("-n", "--lines", type=int, default=50, help="logs: how many lines")
    service.set_defaults(func=cmd_service)

    config = subparsers.add_parser("config", aliases=["c"], help="config file helpers")
    config.add_argument("action", nargs="?", choices=["init", "path", "show"], default="path")
    config.add_argument("--force", action="store_true", help="overwrite an existing config")
    config.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
