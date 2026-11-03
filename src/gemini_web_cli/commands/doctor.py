"""Self checks. Read-only."""

from __future__ import annotations

import asyncio
from typing import Any

import typer

from gemini_web_cli import invocation
from gemini_web_cli.client import cookie_facts, open_client, state_writable
from gemini_web_cli.commands.chats import settings_of
from gemini_web_cli.errors import ToolError
from gemini_web_cli.output import emit


def doctor(
    ctx: typer.Context,
    offline: bool = typer.Option(False, "--offline", help="Skip the authenticated network call."),
) -> None:
    """Check cookies, state directory and authentication."""
    settings = settings_of(ctx)
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    try:
        facts = cookie_facts(settings.browser)
        record("cookies", facts["has_1psid"], f"{facts['browser']}: {facts['cookie_count']} cookies for .google.com")
        record("cookie_1psidts", facts["has_1psidts"], "newest session cookie present")
    except ToolError as exc:
        record("cookies", False, exc.message)

    writable = state_writable(settings.state_dir)
    record("state_dir", writable, str(settings.state_dir))

    if offline:
        record("auth", True, "skipped (--offline)")
    else:
        try:
            detail = asyncio.run(_probe(settings))
            record("auth", True, detail)
        except ToolError as exc:
            record("auth", False, exc.message)

    ok = all(check["ok"] for check in checks)
    emit(
        {"browser": settings.browser, "checks": checks},
        command=invocation.name(),
        meta={"ok": ok},
        pretty=settings.pretty,
    )
    if not ok:
        raise typer.Exit(code=1)


async def _probe(settings) -> str:
    async with open_client(settings) as client:
        chats = client.list_chats() or []
    return f"authenticated, {len(chats)} conversations visible"
