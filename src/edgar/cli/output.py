from __future__ import annotations

import json
from datetime import datetime, timezone


def paginate(items: list, limit: int, offset: int = 0) -> tuple[list, dict]:
    total = len(items)
    chunk = items[offset : offset + limit]
    consumed = offset + len(chunk)
    has_more = consumed < total
    return chunk, {
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": has_more,
        "next_offset": consumed if has_more else None,
    }


def truncate_text(text: str, max_chars: int, offset: int = 0) -> tuple[str, dict]:
    start = min(max(0, offset), len(text))
    end = min(start + max(0, max_chars), len(text))
    chunk = text[start:end]
    has_more = end < len(text)
    return chunk, {
        "offset": start,
        "max_chars": max_chars,
        "chars": len(chunk),
        "total_chars": len(text),
        "has_more": has_more,
        "next_offset": end if has_more else None,
    }


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_envelope(command: str, data: dict, client=None, warnings: list[str] | None = None) -> dict:
    envelope = {
        "ok": True,
        "command": command,
        "retrieved_at": now_utc(),
        "data": data,
    }
    if client is not None:
        envelope["sources"] = client.source_list()
    if warnings:
        envelope["warnings"] = warnings
    return envelope


def make_error(command: str | None, error) -> dict:
    return {
        "ok": False,
        "command": command,
        "retrieved_at": now_utc(),
        "error": error.to_dict(),
    }


def dumps(value, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(value, ensure_ascii=False, indent=2)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
