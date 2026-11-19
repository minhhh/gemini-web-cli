"""Edge-pinned, single-browser Gemini client.

The library scans every installed browser on init and merges the cookie jars.
Two browsers on the same machine usually hold different Google accounts, and a
wrong account answers every call successfully with an empty result. So the scan
is replaced by a loader that reads exactly one browser.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from gemini_web_cli.config import Settings
from gemini_web_cli.errors import ToolError, auth_error

_COOKIE_DOMAIN = ".google.com"
_patched_browser: str | None = None
_cookie_rows: dict[str, list[dict[str, Any]]] = {}


def _browser_cookie3() -> Any:
    try:
        import browser_cookie3 as bc3
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ToolError(
            "missing_dependency",
            "browser-cookie3 is not installed",
            hint='Install with: uv sync --extra dev, or pip install "gemini-webapi[browser]"',
        ) from exc
    return bc3


def _browser_rows(browser: str) -> list[dict[str, Any]]:
    """Cookie rows for one browser, read once per process.

    The credential lookup and the library's loader both call this. Each read can
    prompt for keychain access and decrypt the store again, and a session cookie
    that rotates between the two reads would leave the loader serving a different
    value than the client was built from.
    """
    cached = _cookie_rows.get(browser)
    if cached is not None:
        return cached
    reader = getattr(_browser_cookie3(), browser, None)
    if reader is None:
        raise ToolError(
            "bad_browser",
            f"browser-cookie3 has no reader for {browser}",
            hint="Try --browser edge or --browser firefox",
        )
    rows = [
        {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "expires": cookie.expires,
        }
        for cookie in reader(domain_name=_COOKIE_DOMAIN)
        if not cookie.is_expired()
    ]
    _cookie_rows[browser] = rows
    return rows


def _read_browser_cookies(browser: str) -> dict[str, str]:
    return {row["name"]: row["value"] for row in _browser_rows(browser)}


def _single_browser_loader(browser: str):
    def load(domain_name: str = "", verbose: bool = False) -> dict[str, list[dict[str, Any]]]:
        del domain_name, verbose  # the rows already carry the domain, and verbose is library-only
        try:
            rows = _browser_rows(browser)
        except ToolError:
            return {}
        return {browser: [dict(row) for row in rows]} if rows else {}

    return load


def _install_browser_policy(browser: str) -> None:
    """Replace the library's all-browser scan with a single-browser loader."""
    global _patched_browser
    if _patched_browser == browser:
        return
    import gemini_webapi.utils.get_access_token  # noqa: F401 - ensure the module is loaded

    module = sys.modules["gemini_webapi.utils.get_access_token"]
    module.load_browser_cookies = _single_browser_loader(browser)  # type: ignore[attr-defined]
    _patched_browser = browser


def _session_psid(client: Any) -> str | None:
    return next((str(c.value) for c in client.cookies.jar if c.name == "__Secure-1PSID"), None)


def _source_is_trusted(source: str, session_psid: str | None, supplied_psid: str) -> bool:
    """Decide whether the cookie group behind a session belongs to the chosen browser.

    The library tries its cookie cache before the cookies the caller supplied, and the
    cache lives in this tool's state dir under a file name derived from __Secure-1PSID.
    So a cache hit for the session just read from the chosen browser is ours, and it
    holds the rotated __Secure-1PSIDTS: the freshest credential available. Rejecting it
    would fail every run after the first. A cache hit for any other session, and any
    browser-scan or guest fallback, still means the wrong account is in play.
    """
    if session_psid != supplied_psid:
        return False
    return source == "Base Cookies" or source.startswith("Cache")


def _translate(exc: Exception) -> ToolError:
    from gemini_webapi import exceptions as gexc

    if isinstance(exc, gexc.AuthError):
        return auth_error(
            f"Gemini rejected the session: {exc}",
            hint=(
                "Log in to gemini.google.com in the chosen browser, then re-run. "
                "A rotated __Secure-1PSIDTS is the usual cause."
            ),
        )
    if isinstance(exc, gexc.TemporarilyBlockedError):
        return ToolError("rate_limited", f"Temporarily blocked: {exc}", "Wait and retry later.")
    if isinstance(exc, gexc.UsageLimitExceededError):
        return ToolError("usage_limit", f"Usage limit reached: {exc}")
    if isinstance(exc, gexc.TimeoutError):
        return ToolError("timeout", f"Gemini did not answer in time: {exc}")
    if isinstance(exc, gexc.GeminiError):
        return ToolError("gemini_error", str(exc))
    if isinstance(exc, gexc.APIError):
        return ToolError("api_error", str(exc))
    return ToolError("unexpected", f"{type(exc).__name__}: {exc}")


@asynccontextmanager
async def open_client(settings: Settings) -> AsyncIterator[Any]:
    cookies = _read_browser_cookies(settings.browser)
    if "__Secure-1PSID" not in cookies:
        raise auth_error(
            f"{settings.browser} has no __Secure-1PSID cookie for {_COOKIE_DOMAIN}",
            hint=f"Log in to https://gemini.google.com in {settings.browser}, then re-run.",
        )

    os.environ["GEMINI_COOKIE_PATH"] = str(settings.cookie_dir)
    _install_browser_policy(settings.browser)

    from gemini_webapi import GeminiClient

    client = GeminiClient(
        secure_1psid=cookies["__Secure-1PSID"],
        secure_1psidts=cookies.get("__Secure-1PSIDTS"),
    )
    try:
        await client.init(timeout=settings.timeout, auto_refresh=True)
    except Exception as exc:  # noqa: BLE001 - narrowed by _translate
        raise _translate(exc) from exc

    source = str(getattr(client, "_cookie_source", ""))
    if not _source_is_trusted(source, _session_psid(client), cookies["__Secure-1PSID"]):
        await client.close()
        raise auth_error(
            f"Session resolved from {source or 'unknown source'}, not from the cookies read from {settings.browser}",
            hint=(
                "A merged or foreign cookie jar is in play. Delete the state dir and retry, "
                "or point --browser at the browser logged in to the intended account."
            ),
        )

    try:
        yield client
    finally:
        await client.close()


def run(coro: Coroutine[Any, Any, Any], settings: Settings) -> Any:
    """Run one command coroutine under the global deadline.

    `--timeout` used to bound the handshake only, so a stalled read or delete
    waited on the library's own 450s socket timeout with nothing above it.
    """
    try:
        return asyncio.run(asyncio.wait_for(coro, timeout=settings.timeout))
    except TimeoutError as exc:
        raise ToolError(
            "timeout",
            f"Gemini did not finish within {settings.timeout:g} seconds",
            hint="Retry, or raise --timeout.",
        ) from exc


def recent_chats(client: Any) -> list[Any]:
    """The conversations this session can see.

    `list_chats()` returns None when the account was unavailable at init, which
    is not the same as an account with no conversations. Collapsing the two is
    how a wrong-account session reports an empty history instead of an error.
    """
    chats = client.list_chats()
    if chats is None:
        status = getattr(getattr(client, "account_status", None), "name", "unknown")
        raise auth_error(
            f"Gemini returned no conversation list (account status: {status})",
            hint=(
                "The session cannot list conversations. Cookies from a different Google account "
                "answer every call successfully with an empty result, so check which account is "
                "logged in to the browser named by --browser, then run doctor."
            ),
        )
    return chats


def cookie_facts(browser: str) -> dict[str, Any]:
    """Cookie inventory without touching the network."""
    cookies = _read_browser_cookies(browser)
    return {
        "browser": browser,
        "cookie_count": len(cookies),
        "has_1psid": "__Secure-1PSID" in cookies,
        "has_1psidts": "__Secure-1PSIDTS" in cookies,
    }


def state_writable(directory: Path) -> bool:
    probe = directory / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True
