"""Compatibility for the pinned local Qt WebEngine policy parser.

The ordinary Flask application retains its complete policy. Only responses
delivered by the Desktop-owned WSGI listener use this adapter.
"""
from __future__ import annotations


# Verified in the shipped PySide6 6.11.2 / Chromium 140.0.7339.225 build:
# both names produce parser warnings, neither occurs in allowedFeatures(),
# and PaymentRequest/navigator.usb are absent. Recheck on any Qt upgrade.
_UNRECOGNIZED_BUILD = ("6.11.2", "6.11.2", "140.0.7339.225")
_UNRECOGNIZED_DIRECTIVES = {"payment=()", "usb=()"}


def local_webengine_policy(headers: list[tuple[str, str]], *, qt: str,
                           webengine: str, chromium: str) -> list[tuple[str, str]]:
    """Omit two ineffective directives only for the verified frozen engine."""
    if (qt, webengine, chromium) != _UNRECOGNIZED_BUILD:
        return headers
    result = []
    for key, value in headers:
        if key.lower() == "permissions-policy":
            directives = [part.strip() for part in value.split(",")]
            value = ", ".join(part for part in directives
                              if part not in _UNRECOGNIZED_DIRECTIVES)
        result.append((key, value))
    return result
