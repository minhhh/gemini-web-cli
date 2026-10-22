"""Settings and state paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

APP_NAME: Final = "gemini-web-cli"
ENV_HOME: Final = "GEMINI_WEB_CLI_HOME"
DEFAULT_BROWSER: Final = "edge"
SUPPORTED_BROWSERS: Final = ("edge", "chrome", "brave", "firefox")


def default_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / APP_NAME


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
        return directory

    @property
    def cookie_dir(self) -> Path:
        directory = self.state_dir / "cookies"
        directory.mkdir(parents=True, exist_ok=True)
        return directory
