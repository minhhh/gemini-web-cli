from __future__ import annotations

import json
import sys

import pytest
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from gemini_web_cli import cli
from gemini_web_cli.commands import chats
from gemini_web_cli.errors import ToolError

runner = CliRunner()


def run_main(monkeypatch, capsys, argv):
    """Run through the real entry point so error envelopes are covered."""
    monkeypatch.setattr(sys, "argv", ["gemini-web-cli", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code, capsys.readouterr().out


def _leaf_commands() -> list[tuple[str, list[str]]]:
    """Every leaf command, as (dotted path, names of its required arguments)."""

    def walk(command, path):
        if isinstance(command, TyperGroup):
            for name, child in command.commands.items():
                yield from walk(child, (*path, name))
        else:
            required = [p.name for p in command.params if p.required and p.opts == [p.name]]
            yield ".".join(path), required

    return list(walk(get_command(cli.app), ()))


LEAVES = _leaf_commands()


@pytest.mark.parametrize(("command", "arguments"), LEAVES, ids=[command for command, _ in LEAVES])
def test_every_command_refuses_an_unsupported_browser(monkeypatch, capsys, command, arguments):
    """The browser check lives in settings_of(), which every command must use.

    A command that bypassed it would reach the network and fail differently, so
    this holds the funnel in place as well as the envelope id. Placeholder
    argument values are fine: the check runs before anything reads them.
    """
    code, out = run_main(monkeypatch, capsys, ["--browser", "nope", *command.split("."), *arguments])
    assert code == 1
    payload = json.loads(out)
    assert payload["error"]["code"] == "bad_browser"
    assert payload["command"] == command


def test_error_envelope_command_ignores_global_flag_values(monkeypatch, capsys):
    code, out = run_main(monkeypatch, capsys, ["--home", "/tmp/gw-x", "--browser", "nope", "chats", "list"])
    assert code == 1
    payload = json.loads(out)
    assert payload["error"]["code"] == "bad_browser"
    assert payload["command"] == "chats.list"
    assert "/" not in payload["command"]


def test_error_envelope_command_ignores_positional_arguments(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise ToolError("not_found", "No conversation with id c_doesnotexist")

    monkeypatch.setattr(chats, "_read", boom)
    code, out = run_main(monkeypatch, capsys, ["--browser", "edge", "chats", "read", "c_doesnotexist"])
    assert code == 1
    payload = json.loads(out)
    assert payload["command"] == "chats.read"
    assert "c_doesnotexist" not in payload["command"]


def test_error_envelope_command_single_level(monkeypatch, capsys):
    code, out = run_main(monkeypatch, capsys, ["--timeout", "30", "--browser", "nope", "doctor"])
    assert code == 1
    assert json.loads(out)["command"] == "doctor"


def test_error_envelope_command_falls_back_to_program_name(monkeypatch, capsys):
    code, out = run_main(monkeypatch, capsys, ["--browser", "nope"])
    assert code == 1
    assert json.loads(out)["command"] == "gemini-web-cli"


def test_bare_group_with_bad_browser_is_usage_error(monkeypatch, capsys):
    # No command runs, so the group's no_args_is_help fires before the browser
    # check: usage text on stderr, nothing on stdout. Pinned because it is the
    # one shape where an unsupported browser is not a JSON `bad_browser`.
    code, out = run_main(monkeypatch, capsys, ["--browser", "nope", "chats"])
    assert code == 2
    assert out == ""


def test_pretty_is_honoured_on_root_callback_failures(monkeypatch, capsys):
    _code, out = run_main(monkeypatch, capsys, ["--pretty", "--browser", "nope", "chats", "list"])
    assert out.startswith('{\n  "ok": false')


def test_success_envelope_uses_the_same_command_id(monkeypatch, capsys):
    # Success envelopes derive the id from the same path as failures. Mirrors
    # the funnel test above without touching the network.
    async def no_chats(_settings, _limit):
        return []

    monkeypatch.setattr(chats, "_list", no_chats)
    code, out = run_main(monkeypatch, capsys, ["--home", "/tmp/gw-x", "chats", "list"])
    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["command"] == "chats.list"
    assert payload["meta"] == {"count": 0}


def test_root_help_lists_commands():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for name in ("chats", "doctor"):
        assert name in result.stdout


def test_short_help_flag_at_every_level():
    for args in (["-h"], ["chats", "-h"], ["chats", "read", "-h"], ["doctor", "-h"]):
        result = runner.invoke(cli.app, args)
        assert result.exit_code == 0, args
        assert "Usage:" in result.stdout, args
        assert "-h, --help" in result.stdout, args


def test_version_flag(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["gemini-web-cli", "--version"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip().count(".") == 2


def test_unknown_command_is_usage_error():
    result = runner.invoke(cli.app, ["nope"])
    assert result.exit_code == 2


def test_removed_command_is_usage_error():
    result = runner.invoke(cli.app, ["gems"])
    assert result.exit_code == 2


def test_delete_without_confirmation_emits_json_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["gemini-web-cli", "chats", "delete", "c_test"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"
    assert payload["command"] == "chats.delete"
