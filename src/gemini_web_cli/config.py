"""Settings and state paths."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from gemini_web_cli.errors import ToolError

APP_NAME: Final = "gemini-web-cli"
ENV_HOME: Final = "GEMINI_WEB_CLI_HOME"
DEFAULT_BROWSER: Final = "edge"
SUPPORTED_BROWSERS: Final = ("edge", "chrome", "brave", "firefox")


def _restrict(directory: Path) -> None:
    """Keep the state directory private.

    The Gemini library names its cookie cache after __Secure-1PSID, so a
    world-listable directory leaks the session token through file names alone.
    """
    with contextlib.suppress(OSError):
        directory.chmod(0o700)


def default_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / APP_NAME


def ensure_supported_browser(browser: str) -> None:
    """Reject a browser name no command can use.

    Runs where settings are consumed rather than only in the root callback, so
    the failure carries the full command path even when it is raised by a leaf.
    """
    if browser not in SUPPORTED_BROWSERS:
        raise ToolError(
            "bad_browser",
            f"Unsupported browser: {browser}",
            hint="Choose one of: " + ", ".join(SUPPORTED_BROWSERS),
        )


@dataclass(slots=True, frozen=True)
class Settings:
    browser: str = DEFAULT_BROWSER
    home: Path | None = None
    timeout: float = 90.0
    pretty: bool = False
    debug: bool = False

    @property
    def state_dir(self) -> Path:
        directory = self.home or default_home()
        directory.mkdir(parents=True, exist_ok=True)
        _restrict(directory)
        return directory

    @property
    def cookie_dir(self) -> Path:
        directory = self.state_dir / "cookies"
        directory.mkdir(parents=True, exist_ok=True)
        _restrict(directory)
        return directory
