from __future__ import annotations
from dataclasses import dataclass, field

from backend.app.evidence.catalogue import load_carrier_table, supported_carriers, verified_benefit, benefit_terms

NOT_CONFIRMED = "Not confirmed"

# Benefit evidence and pricing are deliberately separate concerns.
# A carrier is supported here when Ashlar holds a verified structured
# Table of Benefits. Quote eligibility/pricing remains the Quote Engine's job.
SUPPORTED_CARRIERS = supported_carriers()


@dataclass(frozen=True)
class ComparisonRow:
    benefit_code: str
    label: str
    values: dict[str, str]  # plan_key -> display value (or NOT_CONFIRMED)
    evidence: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class ComparisonMatrix:
    plan_keys: list[str]
    plan_labels: dict[str, str]  # plan_key -> "Carrier — Product"
    rows: list[ComparisonRow]
    unsupported_plan_keys: list[str]  # requested plans we hold no TOB evidence for


def build_comparison_matrix(plans: list[dict]) -> ComparisonMatrix:
    """Build rows only from verified carrier benefit tables.

    A plan may have verified benefits without a price (for example Cigna
    Inspire). Such a plan belongs in the verified catalogue, but it is only
    passed here when another deterministic workflow has selected it.
    """
    def has_plan(p):
        table = load_carrier_table(p["carrier"]) or {}
        return any(p["product_code"] in (b.get("values") or {}) for b in table.get("benefits", []))
    supported = [p for p in plans if has_plan(p)]
    unsupported = [p["plan_key"] for p in plans if not has_plan(p)]

    plan_keys = [p["plan_key"] for p in supported]
    plan_labels = {p["plan_key"]: f'{p["insurer"]} — {p["product_name"]}' for p in supported}
    if not supported:
        return ComparisonMatrix(plan_keys=[], plan_labels={}, rows=[], unsupported_plan_keys=unsupported)

    # Merge benefit codes across carriers without ever filling a missing cell
    # from a neighbouring plan or another carrier.
    benefit_index: dict[str, dict] = {}
    for plan in supported:
        table = load_carrier_table(plan["carrier"]) or {}
        for benefit in table.get("benefits") or []:
            if benefit.get("status") != "verified" or not benefit.get("allow_generation", True):
                continue
            code = str(benefit.get("benefit_code") or "")
            if code and code not in benefit_index:
                benefit_index[code] = {
                    "label": benefit.get("label") or code,
                    "order": len(benefit_index),
                }

    rows: list[ComparisonRow] = []
    for code, meta in sorted(benefit_index.items(), key=lambda item: item[1]["order"]):
        values: dict[str, str] = {}
        any_value = False
        evidence = {}
        for plan in supported:
            table = load_carrier_table(plan["carrier"]) or {}
            benefit = verified_benefit(plan["carrier"], plan["product_code"], code)
            value = (benefit.get("values") or {}).get(plan["product_code"]) if benefit else None
            if value:
                values[plan["plan_key"]] = str(value)
                terms = benefit_terms(table, benefit, plan["product_code"])
                if terms:
                    values[plan["plan_key"]] += " — " + "; ".join(terms)
                evidence[plan["plan_key"]] = {
                    "source": table.get("source"), "version": table.get("version"),
                    "page": benefit.get("page"), "currency": table.get("currency", "EUR"),
                    "waiting_period": benefit.get("waiting_period"),
                    "conditions": terms, "benefit_code": code,
                }
                any_value = True
            else:
                values[plan["plan_key"]] = NOT_CONFIRMED
        if any_value:
            rows.append(ComparisonRow(benefit_code=code, label=meta["label"], values=values, evidence=evidence))

    return ComparisonMatrix(
        plan_keys=plan_keys,
        plan_labels=plan_labels,
        rows=rows,
        unsupported_plan_keys=unsupported,
    )


def matrix_to_dict(matrix: ComparisonMatrix) -> dict:
    return {
        "plan_keys": matrix.plan_keys,
        "plan_labels": matrix.plan_labels,
        "rows": [{"benefit_code": r.benefit_code, "label": r.label, "values": r.values, "evidence": r.evidence} for r in matrix.rows],
        "unsupported_plan_keys": matrix.unsupported_plan_keys,
    }
