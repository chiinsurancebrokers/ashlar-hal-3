from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge"


@lru_cache
def greece_profile() -> dict:
    return json.loads((DATA_DIR / "greece.json").read_text(encoding="utf-8"))


@lru_cache
def fairness_rules() -> dict:
    return json.loads((DATA_DIR / "fairness_rules.json").read_text(encoding="utf-8"))


@lru_cache
def international_vs_local() -> dict:
    return json.loads((DATA_DIR / "international_vs_local.json").read_text(encoding="utf-8"))


@lru_cache
def hnwi_signals() -> dict:
    return json.loads((DATA_DIR / "hnwi.json").read_text(encoding="utf-8"))


def greece_indicator(indicator_id: str) -> dict | None:
    for ind in greece_profile()["indicators"]:
        if ind["id"] == indicator_id:
            return ind
    return None


def detect_hnwi(text: str) -> bool:
    signals = hnwi_signals()["signals"]
    low = (text or "").lower()
    return any(s in low for s in signals["en"]) or any(s in low for s in signals["el"])


def fairness_check(generated_text: str) -> list[str]:
    """Cheap guardrail: flag if generated adviser text contains language that
    resembles a prohibited claim. This is a lexical safety net alongside the
    prompt instructions, not a replacement for them."""
    low = (generated_text or "").lower()
    flags = []
    red_flags = {
        "everyone needs": "implies universal necessity of private cover",
        "covers all pre-existing": "overstates pre-existing condition coverage",
        "always better than": "asserts blanket superiority",
        "guarantees immediate": "promises guaranteed immediate treatment",
        "public system is useless": "disparages public healthcare",
        "public healthcare is useless": "disparages public healthcare",
    }
    for phrase, reason in red_flags.items():
        if phrase in low:
            flags.append(f"possible fairness violation ('{phrase}'): {reason}")
    return flags
