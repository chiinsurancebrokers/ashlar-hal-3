"""Robust helpers for parsing JSON returned by Proposal Studio's LLM layer."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_first_json_object(raw: str) -> dict[str, Any]:
    if raw is None:
        raise json.JSONDecodeError("Empty model response", "", 0)
    text = str(raw).strip()
    if not text:
        raise json.JSONDecodeError("Empty model response", text, 0)
    text = _FENCE_RE.sub("", text).strip()
    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for match in re.finditer(r"\{", text):
        try:
            value, _end = decoder.raw_decode(text, idx=match.start())
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(value, dict):
            return value
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("No JSON object found in model response", text, 0)


def parse_json_objects(raw: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    text = _FENCE_RE.sub("", text).strip()
    decoder = json.JSONDecoder()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r"\{", text):
        try:
            value, _end = decoder.raw_decode(text, idx=match.start())
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        try:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def parse_best_json_object(raw: str, *, required_keys: Iterable[str] = ()) -> dict[str, Any]:
    candidates = parse_json_objects(raw)
    if not candidates:
        return parse_first_json_object(raw)
    required = tuple(str(k) for k in required_keys)

    def score(obj: dict[str, Any]) -> tuple[int, int, int]:
        key_hits = sum(1 for k in required if k in obj)
        nonempty_hits = sum(1 for k in required if obj.get(k) not in (None, "", [], {}))
        return key_hits, nonempty_hits, len(obj)

    return max(candidates, key=score)
