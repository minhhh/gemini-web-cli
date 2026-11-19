"""Conversation commands."""

from __future__ import annotations

from typing import Any

import typer

from gemini_web_cli import invocation, serialize
from gemini_web_cli.client import open_client, recent_chats, run
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
    chats, available = run(_list(settings, limit), settings)
    emit(
        {"chats": chats},
        command=invocation.name(),
        meta={"count": len(chats), "available": available, "truncated": available > len(chats)},
        pretty=settings.pretty,
    )


async def _list(settings: Settings, limit: int) -> tuple[list[dict[str, Any]], int]:
    """One page of conversations, plus how many that page holds.

    The library fills its list during init and offers no continuation, so a
    `--limit` above the page size cannot be satisfied. Reporting `available`
    keeps the shortfall visible instead of returning 20 rows for `-n 200`.
    """
    async with open_client(settings) as client:
        infos = recent_chats(client)
        return [serialize.chat_info(info) for info in infos[:limit]], len(infos)


@chats_app.command("read")
def read_command(
    ctx: typer.Context,
    cid: str = typer.Argument(..., help="Conversation id, for example c_0123456789abcdef."),
    turns: int = typer.Option(200, "--turns", min=1, max=2000, help="Maximum turns to fetch."),
    oldest_first: bool = typer.Option(False, "--oldest-first", help="Reverse the default newest-first order."),
) -> None:
    """Read one conversation."""
    settings = settings_of(ctx)
    history = run(_read(settings, cid, turns), settings)
    if oldest_first:
        history["turns"] = list(reversed(history["turns"]))
        history["order"] = "oldest_first"
    emit(
        history,
        command=invocation.name(),
        meta={"turn_count": history["turn_count"], "truncated": history["truncated"]},
        pretty=settings.pretty,
    )


async def _read(settings: Settings, cid: str, turns: int) -> dict[str, Any]:
    """One conversation, flagged when the turn limit cut it short.

    The limit goes to the server, so the response alone cannot show whether
    more turns exist. Asking for one extra and discarding it answers that.
    """
    async with open_client(settings) as client:
        history = await client.read_chat(cid, limit=turns + 1)
    if history is None:
        # The library also returns None while a reply is still generating, or
        # after a parse failure, so this cannot claim the id is gone.
        raise ToolError(
            "not_found",
            f"Gemini returned no turns for {cid}",
            hint=(
                "The id may be wrong, the conversation may be gone, or the last reply may still "
                "be generating. Run chats list to check the id, then retry."
            ),
        )
    payload = serialize.chat_history(history)
    if len(payload["turns"]) > turns:
        payload["turns"] = payload["turns"][:turns]
        payload["turn_count"] = len(payload["turns"])
        payload["truncated"] = True
    return payload


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
    matches, available = run(_search(settings, query, limit), settings)
    emit(
        {"query": query, "chats": matches},
        command=invocation.name(),
        meta={"count": len(matches), "available": available, "truncated": available > len(matches)},
        pretty=settings.pretty,
    )


async def _search(settings: Settings, query: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    needle = query.casefold()
    async with open_client(settings) as client:
        infos = recent_chats(client)
    rows = [
        serialize.chat_info(info)
        for info in infos
        if needle in (getattr(info, "title", "") or "").casefold()
    ]
    return rows[:limit], len(rows)


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
    run(_delete(settings, cid), settings)
    emit({"cid": cid, "deleted": True}, command=invocation.name(), pretty=settings.pretty)


async def _delete(settings: Settings, cid: str) -> None:
    async with open_client(settings) as client:
        await client.delete_chat(cid)
        remaining = await client.read_chat(cid)
    if remaining is not None:
        raise ToolError("delete_failed", f"{cid} still readable after delete")
