"""Tool errors and exit codes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

EXIT_OK: Final = 0
EXIT_ERROR: Final = 1
EXIT_USAGE: Final = 2
EXIT_AUTH: Final = 3


@dataclass(slots=True)
class ToolError(Exception):
    """A failure with a stable code, so callers can branch on it."""

    code: str
    message: str
    hint: str | None = None
    exit_code: int = field(default=EXIT_ERROR)

    def __str__(self) -> str:
        return self.message


def auth_error(message: str, hint: str | None = None) -> ToolError:
    return ToolError("auth_failed", message, hint, EXIT_AUTH)
