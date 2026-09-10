from __future__ import annotations
from dataclasses import dataclass

from backend.app.evidence.morgan_price_2026 import load_table_of_benefits

NOT_CONFIRMED = "Not confirmed"

# Only carriers we currently hold a real, structured Table of Benefits for.
# Adding a new carrier here means loading its TOB into evidence/ in the same
# shape as morgan_price_2026/table_of_benefits.json — never means hand-typing
# numbers into this file.
SUPPORTED_CARRIERS = {"morgan_price"}


@dataclass(frozen=True)
class ComparisonRow:
    benefit_code: str
    label: str
    values: dict[str, str]  # plan_key -> display value (or NOT_CONFIRMED)


@dataclass(frozen=True)
class ComparisonMatrix:
    plan_keys: list[str]
    plan_labels: dict[str, str]  # plan_key -> "Carrier — Product"
    rows: list[ComparisonRow]
    unsupported_plan_keys: list[str]  # requested plans we hold no TOB evidence for


def build_comparison_matrix(plans: list[dict]) -> ComparisonMatrix:
    """plans: list of {"plan_key": str, "carrier": str, "product_code": str,
    "insurer": str, "product_name": str}. Only carriers in SUPPORTED_CARRIERS
    get real rows; everything else is reported as unsupported rather than
    silently skipped, so the caller can tell the client honestly."""
    supported = [p for p in plans if p["carrier"] in SUPPORTED_CARRIERS]
    unsupported = [p["plan_key"] for p in plans if p["carrier"] not in SUPPORTED_CARRIERS]

    plan_keys = [p["plan_key"] for p in supported]
    plan_labels = {p["plan_key"]: f'{p["insurer"]} — {p["product_name"]}' for p in supported}

    if not supported:
        return ComparisonMatrix(plan_keys=[], plan_labels={}, rows=[], unsupported_plan_keys=unsupported)

    tob = load_table_of_benefits()["benefits"]
    rows: list[ComparisonRow] = []
    for b in tob:
        values: dict[str, str] = {}
        any_value = False
        for p in supported:
            v = b["values"].get(p["product_code"])
            if v:
                values[p["plan_key"]] = v
                any_value = True
            else:
                values[p["plan_key"]] = NOT_CONFIRMED
        if any_value:  # skip rows nobody in this comparison has any data for
            rows.append(ComparisonRow(benefit_code=b["benefit_code"], label=b["label"], values=values))

    return ComparisonMatrix(plan_keys=plan_keys, plan_labels=plan_labels, rows=rows, unsupported_plan_keys=unsupported)


def matrix_to_dict(matrix: ComparisonMatrix) -> dict:
    return {
        "plan_keys": matrix.plan_keys,
        "plan_labels": matrix.plan_labels,
        "rows": [{"benefit_code": r.benefit_code, "label": r.label, "values": r.values} for r in matrix.rows],
        "unsupported_plan_keys": matrix.unsupported_plan_keys,
    }
