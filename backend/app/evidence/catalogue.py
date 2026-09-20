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
            "img": ("quotation_required", "No verified GPMI price table loaded; legacy IMG rates are not GPMI prices"),
            "morgan_price": ("verified_rate_table", "Morgan Price 2026 official rate table"),
            "cigna": ("quotation_required", "No verified general Cigna price table loaded"),
        }.get(carrier, ("not_loaded", "No verified price table loaded"))
        for code in codes:
            rows.append({
                "carrier": carrier,
                "carrier_name": table.get("carrier_name") or carrier,
                "product_family": table.get("product_family"),
                "product_code": code,
                "plan_key": f"{carrier}:" + ("gpmi_" if carrier == "img" else "inspire_" if carrier == "cigna" else "") + code,
                "plan_name": (code.replace("_care", "Care").title().replace("care", "Care") if carrier == "cigna" else "GPMI " + code.replace("_", " ").title() if carrier == "img" else code.replace("_", " ").title()),
                "currency": table.get("currency", "EUR"),
                "evidence_scope": "Brochure benefits; acceptance and individual policy terms require insurer confirmation",
                "benefit_evidence_status": "verified",
                "benefit_source": table.get("source"),
                "benefit_version": table.get("version"),
                "pricing_status": pricing[0],
                "pricing_note": pricing[1],
            })
    return rows


def verified_benefit(carrier: str, product_code: str, benefit_code: str) -> dict | None:
    table = load_carrier_table(carrier) or {}
    for row in table.get("benefits", []):
        if (row.get("benefit_code") == benefit_code
                and row.get("status") == "verified"
                and row.get("allow_generation", True)
                and (row.get("values") or {}).get(product_code)):
            return row
    return None


def benefit_terms(table: dict, benefit: dict, product_code: str) -> list[str]:
    terms = list(benefit.get("conditions") or [])
    terms += list((benefit.get("plan_conditions") or {}).get(product_code) or [])
    if benefit.get("waiting_period"):
        terms.append("Waiting period: " + benefit["waiting_period"])
    return list(dict.fromkeys(terms))


REQUIREMENT_BENEFITS = {
    "outpatient_required": ("Out-patient cover", ["outpatient_services_combined"]),
    "maternity_required": ("Routine maternity", ["normal_maternity"]),
    "dental_required": ("Routine dental", ["routine_dental"]),
    "mental_health_required": ("Mental health", ["inpatient_psychiatric", "outpatient_psychiatric"]),
    "wellness_required": ("Wellness screening", ["wellness_screening"]),
    "optical_required": ("Optical benefits", ["optical_glasses"]),
    "evacuation_required": ("Medical evacuation", ["medical_evacuation_transport"]),
    "chronic_required": ("Chronic condition cover", ["inpatient_chronic_conditions", "outpatient_chronic_conditions"]),
}


def catalogue_checklist(carrier: str, product_code: str) -> list[dict]:
    items = []
    for field, (label, codes) in REQUIREMENT_BENEFITS.items():
        if carrier == "cigna" and field == "chronic_required":
            codes = ["chronic_conditions"]
        values = []
        for code in codes:
            row = verified_benefit(carrier, product_code, code)
            values.append(row["values"][product_code] if row else None)
        negative = any(v and v.casefold() == "not covered" for v in values)
        conditional = any(v and ("option" in v.casefold() or "not covered" in v.casefold()) for v in values)
        known = all(v is not None for v in values)
        covered = False if negative else (True if known and not conditional else None)
        items.append({"field": field, "label": label, "covered": covered,
                      "status": "not_covered" if negative else "conditional" if conditional else "verified" if known else "not_confirmed"})
    return items
