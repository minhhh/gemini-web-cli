"""Cookie-source guard in open_client.

The library tries its cookie cache before the cookies the caller supplies, so the
guard has to accept a cache hit that belongs to the chosen browser while still
rejecting a jar that came from somewhere else. A fake client reproduces the
library's cache-first ordering without touching the network or a real browser.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gemini_web_cli import client as client_module
from gemini_web_cli.config import Settings
from gemini_web_cli.errors import ToolError

PSID_A = "psid-account-a"
PSID_B = "psid-account-b"


def _cookie(name: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, value=value)


class FakeClient:
    """Mimics the library's cache-first init, keyed on __Secure-1PSID like the real one."""

    def __init__(self, secure_1psid, secure_1psidts, *, source_override=None, psid_override=None):
        self._supplied = secure_1psid
        self._supplied_ts = secure_1psidts
        self._source_override = source_override
        self._psid_override = psid_override
        self._cookie_source = ""
        self.cookies = SimpleNamespace(jar=[])
        self.closed = False

    async def init(self, timeout=None, auto_refresh=True):
        del timeout, auto_refresh
        cache = Path(client_module.os.environ["GEMINI_COOKIE_PATH"]) / f".cached_cookies_{self._supplied}.json"
        source = "Cache" if cache.is_file() else "Base Cookies"
        psid = self._supplied
        ts = self._supplied_ts
        if source == "Cache":
            cached = {c["name"]: c["value"] for c in json.loads(cache.read_text())}
            psid, ts = cached.get("__Secure-1PSID", psid), cached.get("__Secure-1PSIDTS", ts)
        if self._source_override:
            source = self._source_override
        if self._psid_override:
            psid = self._psid_override
        self._cookie_source = source
        self.cookies = SimpleNamespace(jar=[_cookie("__Secure-1PSID", psid), _cookie("__Secure-1PSIDTS", ts)])

    async def close(self):
        self.closed = True
        cache = Path(client_module.os.environ["GEMINI_COOKIE_PATH"]) / f".cached_cookies_{self._supplied}.json"
        cache.write_text(
            json.dumps(
                [
                    {"name": "__Secure-1PSID", "value": self._supplied},
                    {"name": "__Secure-1PSIDTS", "value": self._supplied_ts},
                ]
            )
        )


@pytest.fixture
def fake_library(monkeypatch):
    """Patch the browser read and the client factory, returning the factory's call list."""
    created = []

    def install(cookies, *, source_override=None, psid_override=None):
        monkeypatch.setattr(client_module, "_read_browser_cookies", lambda _browser: dict(cookies))

        def factory(secure_1psid, secure_1psidts):
            instance = FakeClient(
                secure_1psid,
                secure_1psidts,
                source_override=source_override,
                psid_override=psid_override,
            )
            created.append(instance)
            return instance

        monkeypatch.setattr("gemini_webapi.GeminiClient", factory)

    install.created = created
    return install


def _run(settings):
    async def go():
        async with client_module.open_client(settings) as gemini:
            return gemini._cookie_source

    return asyncio.run(go())


def test_two_runs_against_one_state_dir_both_succeed(tmp_path, fake_library):
    fake_library({"__Secure-1PSID": PSID_A, "__Secure-1PSIDTS": "ts-a"})
    settings = Settings(browser="edge", home=tmp_path)

    assert _run(settings) == "Base Cookies"
    assert _run(settings) == "Cache"
    assert len(fake_library.created) == 2


def test_cache_from_another_browser_is_not_reused(tmp_path, fake_library):
    (tmp_path / "cookies").mkdir()
    (tmp_path / "cookies" / f".cached_cookies_{PSID_A}.json").write_text(
        json.dumps([{"name": "__Secure-1PSID", "value": PSID_A}])
    )
    fake_library({"__Secure-1PSID": PSID_B, "__Secure-1PSIDTS": "ts-b"})

    assert _run(Settings(browser="firefox", home=tmp_path)) == "Base Cookies"


def test_cache_for_a_different_session_is_rejected(tmp_path, fake_library):
    fake_library(
        {"__Secure-1PSID": PSID_A, "__Secure-1PSIDTS": "ts-a"},
        source_override="Cache",
        psid_override=PSID_B,
    )

    with pytest.raises(ToolError) as exc:
        _run(Settings(browser="edge", home=tmp_path))
    assert exc.value.code == "auth_failed"


def test_browser_scan_fallback_is_rejected(tmp_path, fake_library):
    fake_library({"__Secure-1PSID": PSID_A, "__Secure-1PSIDTS": "ts-a"}, source_override="Browser (firefox)")

    with pytest.raises(ToolError) as exc:
        _run(Settings(browser="edge", home=tmp_path))
    assert exc.value.code == "auth_failed"
