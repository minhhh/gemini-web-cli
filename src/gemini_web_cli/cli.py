"""Entry point. One JSON document on stdout per run."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer

from gemini_web_cli import __version__
from gemini_web_cli.commands import doctor as doctor_command
from gemini_web_cli.commands.chats import chats_app
from gemini_web_cli.config import DEFAULT_BROWSER, SUPPORTED_BROWSERS, Settings
from gemini_web_cli.errors import EXIT_ERROR, ToolError
from gemini_web_cli.output import emit_error

# rich_markup_mode=None keeps Typer on click's plain help formatter: no rounded box
# panels around options, commands and errors, no ANSI styling. Typer has no global
# switch and sub-apps do not inherit, so every typer.Typer(...) needs the flag.
app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Manage Gemini conversations from the command line. JSON on stdout, logs on stderr.",
)

_active: dict[str, Settings] = {"settings": Settings()}


def active_settings() -> Settings:
    return _active["settings"]


def configure_logging(debug: bool) -> None:
    try:
        from gemini_webapi import set_log_level
    except ImportError:
        return
    set_log_level("DEBUG" if debug else "WARNING")


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    browser: str = typer.Option(
        DEFAULT_BROWSER,
        "--browser",
        help="Browser whose cookies are used. One of: " + ", ".join(SUPPORTED_BROWSERS) + ".",
    ),
    home: Path | None = typer.Option(None, "--home", help="State directory. Default: ~/.local/state/gemini-web-cli"),
    timeout: float = typer.Option(90.0, "--timeout", min=5.0, help="Seconds to wait for the Gemini handshake."),
    pretty: bool = typer.Option(False, "--pretty", help="Indent JSON output."),
    debug: bool = typer.Option(False, "--debug", help="Verbose logs, extra detail in errors."),
    version: bool = typer.Option(False, "--version", is_eager=True, help="Print the version and exit."),
) -> None:
    """Global options."""
    if version:
        sys.stdout.write(__version__ + "\n")
        raise typer.Exit()
    if browser not in SUPPORTED_BROWSERS:
        raise ToolError(
            "bad_browser",
            f"Unsupported browser: {browser}",
            hint="Choose one of: " + ", ".join(SUPPORTED_BROWSERS),
        )
    settings = Settings(browser=browser, home=home, timeout=timeout, pretty=pretty, debug=debug)
    _active["settings"] = settings
    ctx.obj = settings
    configure_logging(debug)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


app.add_typer(chats_app, name="chats")
app.command("doctor")(doctor_command.doctor)


def _command_name() -> str:
    words = [word for word in sys.argv[1:] if not word.startswith("-")]
    return ".".join(words[:2]) if words else "gemini-web-cli"


def _detail(exc: Exception) -> str | None:
    if not _active["settings"].debug:
        return None
    import traceback

    return "".join(traceback.format_exception(exc))


def main() -> None:
    try:
        app(prog_name="gemini-web-cli")
    except ToolError as exc:
        settings = active_settings()
        emit_error(
            command=_command_name(),
            code=exc.code,
            message=exc.message,
            hint=exc.hint,
            pretty=settings.pretty,
        )
        raise SystemExit(exc.exit_code) from None
    except typer.Exit:
        raise
    except (KeyboardInterrupt, BrokenPipeError):
        raise SystemExit(130) from None
    except Exception as exc:  # noqa: BLE001 - last resort, still machine readable
        settings = active_settings()
        emit_error(
            command=_command_name(),
            code="unexpected",
            message=f"{type(exc).__name__}: {exc}",
            hint="Re-run with --debug for a traceback.",
            detail=_detail(exc),
            pretty=settings.pretty,
        )
        raise SystemExit(EXIT_ERROR) from None


def run(argv: list[str] | None = None) -> Any:  # pragma: no cover - convenience for embedding
    sys.argv = ["gemini-web-cli", *(argv or [])]
    main()
