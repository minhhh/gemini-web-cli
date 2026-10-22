"""Typed Gemini objects to plain JSON."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _iso(timestamp: float | None) -> str | None:
    if not timestamp:
        return None
    moment = datetime.fromtimestamp(float(timestamp), tz=UTC)
    return moment.isoformat().replace("+00:00", "Z")


def chat_info(info: Any) -> dict[str, Any]:
    return {
        "cid": str(getattr(info, "cid", "")),
        "title": getattr(info, "title", "") or "",
        "pinned": bool(getattr(info, "is_pinned", False)),
        "updated_at": _iso(getattr(info, "timestamp", None)),
    }


def turn(item: Any, index: int) -> dict[str, Any]:
    output = getattr(item, "model_output", None)
    images = [
        getattr(image, "url", None) or str(image)
        for image in (getattr(output, "images", None) or [])
    ]
    return {
        "index": index,
        "role": getattr(item, "role", "") or "",
        "text": getattr(item, "text", "") or "",
        "images": images,
    }


def chat_history(history: Any) -> dict[str, Any]:
    turns = [turn(item, index) for index, item in enumerate(getattr(history, "turns", []) or [])]
    return {
        "cid": str(getattr(history, "cid", "")),
        "order": "newest_first",
        "turn_count": len(turns),
        "turns": turns,
    }

