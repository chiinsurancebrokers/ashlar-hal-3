from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.cases.models import AshlarCase, Fact, FactStatus


class PolicyVerdict(str, Enum):
    COVERED = "covered"
    NOT_COVERED = "not_covered"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class PolicyCoverageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: PolicyVerdict
    benefit_key: str
    plan_key: str | None = None
    value: Any = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    reason: str


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


def _negative(value: Any) -> bool:
    if value is False or value == 0:
        return True
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value.strip().casefold())
        return text in {
            "no", "none", "false", "not covered", "excluded", "not included",
            "δεν καλύπτεται", "εξαιρείται", "δεν περιλαμβάνεται",
        }
    if isinstance(value, dict):
        status = value.get("status")
        return _negative(status) if status is not None else False
    return False


def _evidence(fact: Fact) -> dict[str, Any]:
    return {
        "fact_id": str(fact.fact_id),
        "provider": fact.provider,
        "plan_key": fact.plan_key,
        "value": fact.value,
        "source_type": fact.source.source_type.value,
        "source_ref": fact.source.source_ref,
        "document_id": str(fact.source.document_id) if fact.source.document_id else None,
        "page": fact.source.page,
        "quote": fact.source.quote,
    }


class PolicyEngine:
    """Answer policy questions from verified facts only.

    The engine is deliberately deterministic. It does not infer coverage from a
    brochure fragment, model memory, or a health recommendation. If verified
    policy evidence is absent or contradictory it returns UNKNOWN/CONFLICT.
    """

    def check_benefit(
        self,
        *,
        case: AshlarCase,
        benefit_key: str,
        plan_key: str | None = None,
    ) -> PolicyCoverageResult:
        slug = _slug(benefit_key.removeprefix("benefit."))
        normalized = f"benefit.{slug}" if slug else "benefit"

        candidate_plan = str(plan_key or "").strip() or None
        if candidate_plan is None and len(case.selected_plan_keys) == 1:
            candidate_plan = case.selected_plan_keys[0]

        facts = [
            fact for fact in case.facts
            if fact.status == FactStatus.VERIFIED
            and fact.key == normalized
            and (candidate_plan is None or fact.plan_key == candidate_plan)
        ]

        if not facts:
            return PolicyCoverageResult(
                verdict=PolicyVerdict.UNKNOWN,
                benefit_key=normalized,
                plan_key=candidate_plan,
                reason="No verified policy fact is available for this benefit.",
            )

        values = {_canonical(f.value) for f in facts}
        evidence = [_evidence(f) for f in facts]
        if len(values) > 1:
            return PolicyCoverageResult(
                verdict=PolicyVerdict.CONFLICT,
                benefit_key=normalized,
                plan_key=candidate_plan,
                evidence=evidence,
                reason="Verified policy sources disagree; coverage must not be inferred until the conflict is resolved.",
            )

        winner = facts[-1]
        if _negative(winner.value):
            return PolicyCoverageResult(
                verdict=PolicyVerdict.NOT_COVERED,
                benefit_key=normalized,
                plan_key=winner.plan_key or candidate_plan,
                value=winner.value,
                evidence=evidence,
                reason="Verified policy evidence explicitly records this benefit as not covered.",
            )

        return PolicyCoverageResult(
            verdict=PolicyVerdict.COVERED,
            benefit_key=normalized,
            plan_key=winner.plan_key or candidate_plan,
            value=winner.value,
            evidence=evidence,
            reason="Verified policy evidence records coverage for this benefit; the value/terms remain authoritative.",
        )


_POLICY_ENGINE = PolicyEngine()


def get_policy_engine() -> PolicyEngine:
    return _POLICY_ENGINE
