from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class PolicyIssue(BaseModel):
    severity: Literal["warn", "block"]
    issue_type: str
    benefit_code: str | None = None
    evidence: str


class PolicyAnalysis(BaseModel):
    verdict: Literal["PASS", "WARN", "BLOCK"]
    confirmed_facts: list[dict[str, Any]] = Field(default_factory=list)
    unconfirmed_facts: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[PolicyIssue] = Field(default_factory=list)
    safe_for_comparison: bool


def analyze_current_policy(payload: dict[str, Any] | None) -> PolicyAnalysis:
    """Audit Proposal Studio output without inventing policy terms.

    Only explicit confirmed rows become confirmed facts. Opposing statuses for
    the same benefit block row-by-row comparison until the evidence is reconciled.
    """
    payload = payload or {}
    rows = payload.get("benefit_rows") or payload.get("benefits") or []
    confirmed: list[dict[str, Any]] = []
    unconfirmed: list[dict[str, Any]] = []
    issues: list[PolicyIssue] = []
    seen: dict[str, set[str]] = {}

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        code = str(row.get("benefit_code") or row.get("code") or "").strip()
        status = str(row.get("status") or "unconfirmed").strip().lower()
        if code:
            seen.setdefault(code, set()).add(status)
        if status == "confirmed":
            confirmed.append(row)
        else:
            unconfirmed.append(row)

    for code, statuses in seen.items():
        if "confirmed" in statuses and "not_covered" in statuses:
            issues.append(PolicyIssue(
                severity="block", issue_type="contradictory_benefit_evidence", benefit_code=code,
                evidence="The same benefit is marked both confirmed and not_covered in the supplied policy analysis.",
            ))

    if not rows:
        issues.append(PolicyIssue(
            severity="warn", issue_type="no_structured_benefit_rows", benefit_code=None,
            evidence="No structured benefit rows were supplied; HAL must not infer missing policy terms.",
        ))

    blocked = any(i.severity == "block" for i in issues)
    verdict = "BLOCK" if blocked else ("WARN" if issues or unconfirmed else "PASS")
    return PolicyAnalysis(
        verdict=verdict, confirmed_facts=confirmed, unconfirmed_facts=unconfirmed,
        issues=issues, safe_for_comparison=not blocked,
    )
