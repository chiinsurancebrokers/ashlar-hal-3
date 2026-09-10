from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).resolve().parents[3] / "data" / "evidence" / "carrier_profile.json"


@lru_cache
def load_carrier_profiles() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def carrier_profile(carrier: str) -> dict:
    return load_carrier_profiles().get(carrier, {})
