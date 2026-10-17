"""Deduplicate two verified parser diagnostics; never change remote headers."""
from .policy import _UNRECOGNIZED_BUILD

KNOWN_MESSAGES = frozenset({
    "Error with Permissions-Policy header: Unrecognized feature: 'payment'.",
    "Error with Permissions-Policy header: Unrecognized feature: 'usb'.",
})


class ServerPolicyDiagnostics:
    def __init__(self, versions):
        self.verified = tuple(versions) == _UNRECOGNIZED_BUILD
        self.counts = {}

    def repeated(self, message: str, *, warning: bool) -> bool:
        if not self.verified or not warning or message not in KNOWN_MESSAGES:
            return False
        self.counts[message] = self.counts.get(message, 0) + 1
        return self.counts[message] > 1
