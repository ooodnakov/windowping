"""Was it the network or the provider?

A ping that fails because the tunnel dropped says nothing about the account, and
treating both the same way produces two bad outcomes: the history fills with
alarming errors that are really one router reboot, and the retry policy either
retries things that will never work (a 401) or gives up on things that would
succeed a second later (a reset connection).

``classify`` answers that question from the error text. It is deliberately
conservative: anything that names a connection-level failure is ``network``,
everything else is ``provider``, and an error that cannot be read is left
unclassified rather than guessed.
"""

from __future__ import annotations

NETWORK_MARKERS = (
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname",
    "connection reset by peer",
    "connection refused",
    "connection aborted",
    "connection error",
    "broken pipe",
    "network is unreachable",
    "no route to host",
    "handshake operation timed out",
    "unexpected_eof",
    "eof occurred",
    "remote end closed connection",
    "timed out",
    "timeout",
    "ssl",
)

PROVIDER_MARKERS = (
    "http 4",
    "http 5",
    "status 4",
    "status 5",
    "unauthorized",
    "forbidden",
    "invalid",
    "no api key",
    "no apikey",
    "no api_key",
    "not supported",
    "quota",
)


def classify(message: str | None) -> str | None:
    """``"network"``, ``"provider"`` or None when there is nothing to classify."""
    if not message:
        return None
    lowered = str(message).lower()
    if any(marker in lowered for marker in NETWORK_MARKERS):
        return "network"
    if any(marker in lowered for marker in PROVIDER_MARKERS):
        return "provider"
    return "provider"


def is_network(message: str | None) -> bool:
    """True when retrying the same request later is a reasonable idea."""
    return classify(message) == "network"
