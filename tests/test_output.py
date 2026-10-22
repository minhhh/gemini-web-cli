from __future__ import annotations

import json

from gemini_web_cli.output import emit, emit_error


def test_emit_success_envelope(capsys):
    emit({"chats": []}, command="chats.list", meta={"count": 0})
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "command": "chats.list", "data": {"chats": []}, "meta": {"count": 0}}


def test_emit_error_envelope(capsys):
    emit_error(command="chats.read", code="not_found", message="missing", hint="list first")
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == {"code": "not_found", "message": "missing", "hint": "list first"}


def test_pretty_is_valid_json(capsys):
    emit({"a": 1}, command="x", pretty=True)
    text = capsys.readouterr().out
    assert "\n  " in text
    assert json.loads(text)["data"] == {"a": 1}
