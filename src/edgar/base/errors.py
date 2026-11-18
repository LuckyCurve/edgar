from __future__ import annotations


class EdgarError(Exception):
    """An error with a stable code and an actionable hint."""

    code = "ERROR"
    exit_code = 1

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out


class UsageError(EdgarError):
    code = "USAGE"
    exit_code = 2


class NotFoundError(EdgarError):
    code = "NOT_FOUND"
    exit_code = 3


class AmbiguousError(EdgarError):
    code = "AMBIGUOUS"
    exit_code = 3


class NetworkError(EdgarError):
    code = "NETWORK"
    exit_code = 4


class BlockedError(NetworkError):
    code = "SEC_BLOCKED"
    exit_code = 4


class ParseError(EdgarError):
    code = "PARSE"
    exit_code = 5
