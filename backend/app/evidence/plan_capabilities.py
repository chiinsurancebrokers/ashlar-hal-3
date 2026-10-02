from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

CAPABILITY_FILE = Path(__file__).resolve().parents[3] / "data" / "evidence" / "plan_capabilities.json"


@lru_cache
def load_plan_capabilities() -> dict:
    return json.loads(CAPABILITY_FILE.read_text(encoding="utf-8"))


def plan_capability(carrier: str, product_code: str, requirement_field: str) -> bool | None:
    """Return a verified capability verdict when one is explicitly known.

    True/False are evidence-backed hard facts. None means unknown and must
    never be silently converted into either covered or not covered.
    """
    raw = load_plan_capabilities().get(carrier, {}).get(product_code, {}).get(requirement_field)
    return raw if isinstance(raw, bool) else None


def plan_capability_meta(carrier: str, product_code: str) -> dict:
    return load_plan_capabilities().get(carrier, {}).get(product_code, {})
