"""Which command is running, for envelopes built after click has unwound."""

from __future__ import annotations

import typer

FALLBACK: str = "gemini-web-cli"

_path: list[str] = []


def record(ctx: typer.Context) -> None:
    """Remember the command path of the invocation in progress.

    Rebuilt from the context chain rather than from sys.argv: argv also carries
    global option values, and those used to end up in the envelope's command
    field. Called from the root callback and from every command's settings
    accessor.
    """
    names: list[str] = []
    node: typer.Context | None = ctx
    while node is not None and node.parent is not None:
        if node.info_name:
            names.append(node.info_name)
        node = node.parent
    if not names and ctx.invoked_subcommand:
        names.append(ctx.invoked_subcommand)
    _path[:] = names[::-1]


def name() -> str:
    """Dotted command id, or the program name when nothing was invoked."""
    return ".".join(_path) or FALLBACK


def clear() -> None:
    """Forget the recorded path.

    Called at entry so an embedded run() cannot inherit the previous
    invocation's id if an exception escapes before any callback records.
    """
    _path.clear()
