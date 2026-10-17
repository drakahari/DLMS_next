"""Presentation tickets, separate from durable operation/transaction identities."""
from dataclasses import dataclass


@dataclass
class OperationFeedback:
    serial: int = 0
    action: str = ""
    message: str = ""
    severity: str = "info"

    def begin(self, action: str) -> int:
        self.serial += 1
        self.action, self.message, self.severity = action, "", "info"
        return self.serial

    def update(self, ticket: int, message: str, severity: str = "info") -> bool:
        if ticket != self.serial:
            return False
        if severity not in {"info", "success", "warning", "error"}:
            raise ValueError("Unknown feedback severity")
        self.message, self.severity = message, severity
        return True
