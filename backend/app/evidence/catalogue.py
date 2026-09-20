from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "data" / "evidence"
CARRIER_TABLES = {
    "morgan_price": ROOT / "morgan_price_2026" / "table_of_benefits.json",
    "img": ROOT / "img_gpmi" / "table_of_benefits.json",
    "cigna": ROOT / "cigna_inspire_2026" / "table_of_benefits.json",
}


@lru_cache(maxsize=None)
def load_carrier_table(carrier: str) -> dict | None:
    path = CARRIER_TABLES.get(str(carrier or "").casefold())
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def supported_carriers() -> set[str]:
    return {carrier for carrier, path in CARRIER_TABLES.items() if path.exists()}


def verified_plan_catalogue() -> list[dict]:
    rows: list[dict] = []
    for carrier in sorted(supported_carriers()):
        table = load_carrier_table(carrier) or {}
        codes = list(table.get("plan_codes") or [])
        if not codes and table.get("benefits"):
            codes = list((table["benefits"][0].get("values") or {}).keys())
        pricing = {
            "img": ("testing_legacy_rates", "IMG Europe/Zone A 2025 legacy rate table"),
            "morgan_price": ("verified_rate_table", "Morgan Price 2026 official rate table"),
            "cigna": ("quotation_required", "No verified general Cigna price table loaded"),
        }.get(carrier, ("not_loaded", "No verified price table loaded"))
        for code in codes:
            rows.append({
                "carrier": carrier,
                "carrier_name": table.get("carrier_name") or carrier,
                "product_family": table.get("product_family"),
                "product_code": code,
                "plan_key": f"{carrier}:{code}",
                "plan_name": code.replace("_", " ").title(),
                "benefit_evidence_status": "verified",
                "benefit_source": table.get("source"),
                "benefit_version": table.get("version"),
                "pricing_status": pricing[0],
                "pricing_note": pricing[1],
            })
    return rows
