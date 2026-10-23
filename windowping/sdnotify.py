"""Minimal sd_notify: tell systemd we are alive, without a dependency.

systemd passes ``$NOTIFY_SOCKET`` and expects datagrams there. ``Type=notify``
needs ``READY=1`` or the start job fails; ``WatchdogSec=`` needs a ``WATCHDOG=1``
often enough or the unit is restarted. Both are a few bytes over a unix socket,
so pulling in a package for it would be silly.

Everything is a no-op when the variable is absent, which is the case when the
watcher runs from a terminal or under a cron-style runner.
"""

from __future__ import annotations

import os
import socket

READY = "READY=1"
WATCHDOG = "WATCHDOG=1"
STOPPING = "STOPPING=1"


def enabled() -> bool:
    return bool(os.environ.get("NOTIFY_SOCKET"))


def notify(message: str) -> bool:
    """Send one datagram to systemd. Returns True when it was delivered."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    # An abstract socket is written "@name" but addressed "\0name".
    target = "\0" + address[1:] if address.startswith("@") else address
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(target)
        sock.sendall(message.encode())
    except OSError:
        return False
    finally:
        sock.close()
    return True


def ready() -> bool:
    return notify(READY)


def watchdog() -> bool:
    return notify(WATCHDOG)


def stopping() -> bool:
    return notify(STOPPING)
