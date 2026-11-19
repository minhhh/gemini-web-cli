"""Cookie policy and the request deadline.

The library tries its cookie cache before the cookies the caller supplies, so the
guard has to accept a cache hit that belongs to the chosen browser while still
rejecting a jar that came from somewhere else. A fake client reproduces the
library's cache-first ordering without touching the network or a real browser.

The second half covers the other half of the invariant: only the browser named on
the command line is read, the library's all-browser scan is replaced, and the
store is read once per process.
"""

from __future__ import annotations

import asyncio
import json
import sys
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


class BrowserCookie:
    def __init__(self, name: str, value: str, expired: bool = False) -> None:
        self.name = name
        self.value = value
        self.domain = ".google.com"
        self.path = "/"
        self.expires = 0
        self._expired = expired

    def is_expired(self) -> bool:
        return self._expired


@pytest.fixture
def fake_browser(monkeypatch):
    """A stand-in browser_cookie3 module that records which readers ran."""
    calls: list[str] = []

    def edge(**_kw):
        calls.append("edge")
        return [
            BrowserCookie("__Secure-1PSID", "psid"),
            BrowserCookie("__Secure-1PSIDTS", "psidts"),
            BrowserCookie("stale", "expired-value", expired=True),
        ]

    def firefox(**_kw):
        calls.append("firefox")
        return []

    module = SimpleNamespace(edge=edge, firefox=firefox)
    monkeypatch.setitem(sys.modules, "browser_cookie3", module)
    monkeypatch.setattr(client_module, "_cookie_rows", {})
    monkeypatch.setattr(client_module, "_patched_browser", None)
    # The policy patch writes to the real library module. Recording the current
    # loader lets monkeypatch put it back when the test ends.
    import gemini_webapi  # noqa: F401 - ensures the submodule is importable

    library = sys.modules["gemini_webapi.utils.get_access_token"]
    monkeypatch.setattr(library, "load_browser_cookies", library.load_browser_cookies)
    return calls


def test_cookie_store_is_read_once(fake_browser):
    calls = fake_browser
    first = client_module._read_browser_cookies("edge")
    second = client_module._read_browser_cookies("edge")
    assert first == second
    assert calls == ["edge"]
    assert "stale" not in first


def test_loader_serves_only_the_chosen_browser(fake_browser):
    calls = fake_browser
    rows = client_module._single_browser_loader("edge")()
    assert set(rows) == {"edge"}
    assert [row["name"] for row in rows["edge"]] == ["__Secure-1PSID", "__Secure-1PSIDTS"]
    assert "firefox" not in calls


@pytest.mark.usefixtures("fake_browser")
def test_patch_lands_on_the_library_module():
    import gemini_webapi  # noqa: F401 - ensures the submodule exists

    client_module._install_browser_policy("edge")
    module = sys.modules["gemini_webapi.utils.get_access_token"]
    assert module.load_browser_cookies(domain_name=".google.com").keys() == {"edge"}

    # A later command in the same process with another browser must repatch,
    # not keep serving the first one.
    client_module._install_browser_policy("firefox")
    assert module.load_browser_cookies() == {}


@pytest.mark.usefixtures("fake_browser")
def test_open_client_refuses_a_session_without_1psid(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys.modules["browser_cookie3"],
        "edge",
        lambda **_kw: [BrowserCookie("NID", "no-session-cookie")],
    )

    async def enter():
        async with client_module.open_client(Settings(home=tmp_path)):
            raise AssertionError("open_client yielded without a session cookie")

    with pytest.raises(ToolError) as excinfo:
        asyncio.run(enter())
    assert excinfo.value.code == "auth_failed"
    assert excinfo.value.exit_code == 3


def test_recent_chats_rejects_a_missing_list():
    fake = SimpleNamespace(list_chats=lambda: None, account_status=SimpleNamespace(name="UNAVAILABLE"))
    with pytest.raises(ToolError) as excinfo:
        client_module.recent_chats(fake)
    assert excinfo.value.code == "auth_failed"
    assert "UNAVAILABLE" in excinfo.value.message


def test_run_enforces_the_command_deadline():
    async def slow():
        await asyncio.sleep(5)

    with pytest.raises(ToolError) as excinfo:
        client_module.run(slow(), Settings(timeout=0.05))
    assert excinfo.value.code == "timeout"
