"""JSON envelope on stdout, one document per invocation."""

from __future__ import annotations

import json
import sys
from typing import Any


def _dumps(payload: dict[str, Any], pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def emit(
    data: Any,
    *,
    command: str,
    meta: dict[str, Any] | None = None,
    pretty: bool = False,
) -> None:
    payload: dict[str, Any] = {"ok": True, "command": command, "data": data}
    if meta:
        payload["meta"] = meta
    sys.stdout.write(_dumps(payload, pretty) + "\n")
    sys.stdout.flush()


def emit_error(
    *,
    command: str,
    code: str,
    message: str,
    hint: str | None = None,
    detail: str | None = None,
    pretty: bool = False,
) -> None:
    error: dict[str, Any] = {"code": code, "message": message}
    if hint:
        error["hint"] = hint
    if detail:
        error["detail"] = detail
    payload = {"ok": False, "command": command, "error": error}
    sys.stdout.write(_dumps(payload, pretty) + "\n")
    sys.stdout.flush()
