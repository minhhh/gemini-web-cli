"""Edge-pinned, single-browser Gemini client.

The library scans every installed browser on init and merges the cookie jars.
Two browsers on the same machine usually hold different Google accounts, and a
wrong account answers every call successfully with an empty result. So the scan
is replaced by a loader that reads exactly one browser.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from gemini_web_cli.config import Settings
from gemini_web_cli.errors import ToolError, auth_error

_COOKIE_DOMAIN = ".google.com"
_PATCHED = False


def _read_browser_cookies(browser: str) -> dict[str, str]:
    try:
        import browser_cookie3 as bc3
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ToolError(
            "missing_dependency",
            "browser-cookie3 is not installed",
            hint='Install with: uv sync --extra dev, or pip install "gemini-webapi[browser]"',
        ) from exc

    reader = getattr(bc3, browser, None)
    if reader is None:
        raise ToolError(
            "bad_browser",
            f"browser-cookie3 has no reader for {browser}",
            hint="Try --browser edge or --browser firefox",
        )
    jar = reader(domain_name=_COOKIE_DOMAIN)
    return {cookie.name: cookie.value for cookie in jar if not cookie.is_expired()}


def _single_browser_loader(browser: str):
    def load(domain_name: str = "", verbose: bool = False) -> dict[str, list[dict[str, Any]]]:
        del verbose  # part of the library's loader signature
        try:
            jar = getattr(__import__("browser_cookie3"), browser)(domain_name=domain_name or _COOKIE_DOMAIN)
        except Exception:  # noqa: BLE001 - loader contract swallows reader failures
            return {}
        rows = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires,
            }
            for cookie in jar
            if not cookie.is_expired()
        ]
        return {browser: rows} if rows else {}

    return load


def _install_browser_policy(browser: str) -> None:
    """Replace the library's all-browser scan with a single-browser loader."""
    global _PATCHED
    if _PATCHED:
        return
    import gemini_webapi.utils.get_access_token  # noqa: F401 - ensure the module is loaded

    module = sys.modules["gemini_webapi.utils.get_access_token"]
    module.load_browser_cookies = _single_browser_loader(browser)  # type: ignore[attr-defined]
    _PATCHED = True


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
    if not source.startswith("Base Cookies"):
        await client.close()
        raise auth_error(
            f"Session resolved from {source or 'unknown source'}, not from the supplied cookies",
            hint="A cached or merged cookie jar is in play. Delete the state dir and retry.",
        )

    try:
        yield client
    finally:
        await client.close()


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
