from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import Fact, FactSource, FactSourceType, FactStatus


def _source(document: str, page: int) -> FactSource:
    return FactSource(
        source_type=FactSourceType.CARRIER_DOCUMENT,
        source_name=document,
        page=page,
    )


def test_fact_ledger_detects_conflicting_verified_facts():
    ledger = FactLedger()

    ledger.add(
        Fact(
            key="annual_limit",
            value=2_000_000,
            currency="EUR",
            provider="Carrier A",
            plan="Executive",
            status=FactStatus.VERIFIED,
            source=_source("TOB.pdf", 14),
        )
    )
    result = ledger.add(
        Fact(
            key="annual_limit",
            value=1_500_000,
            currency="EUR",
            provider="Carrier A",
            plan="Executive",
            status=FactStatus.VERIFIED,
            source=_source("Issued Quote.pdf", 6),
        )
    )

    assert result.has_conflict is True
    assert len(result.conflicts) == 1
    assert result.conflicts[0].key == "annual_limit"


def test_fact_ledger_same_value_does_not_create_conflict():
    ledger = FactLedger()
    first = Fact(
        key="deductible",
        value=500,
        currency="EUR",
        provider="Carrier A",
        plan="Executive",
        status=FactStatus.VERIFIED,
        source=_source("TOB.pdf", 2),
    )
    second = Fact(
        key="deductible",
        value=500,
        currency="EUR",
        provider="Carrier A",
        plan="Executive",
        status=FactStatus.VERIFIED,
        source=_source("Quote.pdf", 1),
    )

    ledger.add(first)
    result = ledger.add(second)

    assert result.has_conflict is False
    assert ledger.latest("deductible", provider="Carrier A", plan="Executive").value == 500


def test_unverified_fact_does_not_override_verified_fact():
    ledger = FactLedger()
    verified = Fact(
        key="annual_limit",
        value=2_000_000,
        provider="Carrier A",
        plan="Executive",
        status=FactStatus.VERIFIED,
        source=_source("TOB.pdf", 14),
    )
    inferred = Fact(
        key="annual_limit",
        value=3_000_000,
        provider="Carrier A",
        plan="Executive",
        status=FactStatus.INFERRED,
        source=FactSource(
            source_type=FactSourceType.AI_INFERENCE,
            source_name="LLM extraction",
        ),
    )

    ledger.add(verified)
    ledger.add(inferred)

    assert ledger.preferred("annual_limit", provider="Carrier A", plan="Executive").value == 2_000_000
