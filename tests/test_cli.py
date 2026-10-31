from __future__ import annotations

import json
import sys

import pytest
from typer.testing import CliRunner

from gemini_web_cli import cli

runner = CliRunner()


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
