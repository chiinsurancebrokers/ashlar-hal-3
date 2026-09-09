from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import csv
import json

RATE_DIR = Path(__file__).resolve().parents[3] / "data" / "rates"
OFFICIAL_FILE = RATE_DIR / "morgan_price_2026_official.csv"
LEGACY_FILE = RATE_DIR / "legacy_april_img_2025.csv"
CARD_META_FILE = Path(__file__).resolve().parents[3] / "data" / "ui" / "plan_cards.json"


@dataclass(frozen=True)
class RateRecord:
    carrier: str
    carrier_name: str
    rate_version: str
    area: str
    area_label: str
    age_min: int
    age_max: int
    product_code: str
    product_name: str
    annual_premium: float
    currency: str
    official: bool
    source: str


@lru_cache
def load_card_meta() -> dict:
    return json.loads(CARD_META_FILE.read_text(encoding="utf-8"))


@lru_cache
def load_rates() -> tuple[RateRecord, ...]:
    records: list[RateRecord] = []

    with OFFICIAL_FILE.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            records.append(RateRecord(
                carrier=row["carrier"], carrier_name=row["carrier_name"],
                rate_version=row["rate_version"], area=row["area"],
                area_label=row["area_label"], age_min=int(row["age_min"]),
                age_max=int(row["age_max"]), product_code=row["product_code"],
                product_name=row["product_name"], annual_premium=float(row["annual_premium"]),
                currency=row["currency"], official=True, source=row["source"],
            ))

    with LEGACY_FILE.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            records.append(RateRecord(
                carrier=row["carrier"], carrier_name=row["carrier_name"],
                rate_version=row["rate_version"], area=row["area"],
                area_label=row["area"], age_min=int(row["age_min"]),
                age_max=int(row["age_max"]), product_code=row["product_code"],
                product_name=row["product_name"], annual_premium=float(row["annual_premium"]),
                currency=row["currency"], official=False,
                source=row.get("rate_note") or "Legacy rate table",
            ))

    return tuple(records)


def rates_for(area: str, age: int) -> list[RateRecord]:
    return [r for r in load_rates() if r.area == area and r.age_min <= age <= r.age_max]


def current_versions() -> list[dict]:
    seen: dict[tuple[str, str], dict] = {}
    for r in load_rates():
        key = (r.carrier, r.rate_version)
        if key not in seen:
            seen[key] = {
                "carrier": r.carrier, "carrier_name": r.carrier_name,
                "rate_version": r.rate_version,
                "status": "official" if r.official else "legacy_unverified",
                "source": r.source,
            }
    return list(seen.values())
