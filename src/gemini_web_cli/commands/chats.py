"""Conversation commands."""

from __future__ import annotations

import asyncio
from typing import Any

import typer

from gemini_web_cli import invocation, serialize
from gemini_web_cli.client import open_client
from gemini_web_cli.config import Settings, ensure_supported_browser
from gemini_web_cli.errors import ToolError
from gemini_web_cli.output import emit

chats_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="List, read, search and delete Gemini conversations.",
)


def settings_of(ctx: typer.Context) -> Settings:
    """Settings for the running command.

    Records the command path first, so any failure reports a stable id, then
    rejects a browser name no command can use. Every command calls this before
    touching the network, which keeps both guarantees in one place.
    """
    invocation.record(ctx)
    settings = ctx.obj
    if not isinstance(settings, Settings):
        raise ToolError("no_context", "Settings were not initialised", hint="Run through the CLI entry point")
    ensure_supported_browser(settings.browser)
    return settings


@chats_app.command("list")
def list_command(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=200, help="Maximum conversations to return."),
) -> None:
    """List recent conversations, newest first."""
    settings = settings_of(ctx)
    chats = asyncio.run(_list(settings, limit))
    emit({"chats": chats}, command=invocation.name(), meta={"count": len(chats)}, pretty=settings.pretty)


async def _list(settings: Settings, limit: int) -> list[dict[str, Any]]:
    async with open_client(settings) as client:
        infos = client.list_chats() or []
        return [serialize.chat_info(info) for info in infos[:limit]]


@chats_app.command("read")
def read_command(
    ctx: typer.Context,
    cid: str = typer.Argument(..., help="Conversation id, for example c_0123456789abcdef."),
    turns: int = typer.Option(200, "--turns", min=1, max=2000, help="Maximum turns to fetch."),
    oldest_first: bool = typer.Option(False, "--oldest-first", help="Reverse the default newest-first order."),
) -> None:
    """Read one conversation."""
    settings = settings_of(ctx)
    history = asyncio.run(_read(settings, cid, turns))
    if oldest_first:
        history["turns"] = list(reversed(history["turns"]))
        history["order"] = "oldest_first"
    emit(history, command=invocation.name(), meta={"turn_count": history["turn_count"]}, pretty=settings.pretty)


async def _read(settings: Settings, cid: str, turns: int) -> dict[str, Any]:
    async with open_client(settings) as client:
        history = await client.read_chat(cid, limit=turns)
    if history is None:
        raise ToolError(
            "not_found",
            f"No conversation with id {cid}",
            hint="Run gemini-web-cli chats list to get valid ids.",
        )
    return serialize.chat_history(history)


@chats_app.command("search")
def search_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Case-insensitive substring match."),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=200),
) -> None:
    """Search conversation titles.

    Title matching only for now. Full-text search needs a local archive.
    """
    settings = settings_of(ctx)
    matches = asyncio.run(_search(settings, query, limit))
    emit(
        {"query": query, "chats": matches},
        command=invocation.name(),
        meta={"count": len(matches)},
        pretty=settings.pretty,
    )


async def _search(settings: Settings, query: str, limit: int) -> list[dict[str, Any]]:
    needle = query.casefold()
    async with open_client(settings) as client:
        infos = client.list_chats() or []
    rows = [
        serialize.chat_info(info)
        for info in infos
        if needle in (getattr(info, "title", "") or "").casefold()
    ]
    return rows[:limit]


@chats_app.command("delete")
def delete_command(
    ctx: typer.Context,
    cid: str = typer.Argument(..., help="Conversation id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the deletion. Destructive and permanent."),
) -> None:
    """Delete one conversation server-side."""
    settings = settings_of(ctx)
    if not yes:
        raise ToolError(
            "confirmation_required",
            f"Refusing to delete {cid} without --yes",
            hint="Re-run with --yes. Deletion is permanent and there is no undo.",
        )
    asyncio.run(_delete(settings, cid))
    emit({"cid": cid, "deleted": True}, command=invocation.name(), pretty=settings.pretty)


async def _delete(settings: Settings, cid: str) -> None:
    async with open_client(settings) as client:
        await client.delete_chat(cid)
        remaining = await client.read_chat(cid)
    if remaining is not None:
        raise ToolError("delete_failed", f"{cid} still readable after delete")
