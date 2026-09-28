from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import Fact, FactSource, FactSourceType, FactStatus


def _fact(*, value: str, source_type: FactSourceType, source_ref: str) -> Fact:
    return Fact(
        subject="plan:carrier:executive",
        key="annual_limit",
        value=value,
        plan_key="carrier:executive",
        status=FactStatus.EXTRACTED,
        source=FactSource(source_type=source_type, source_ref=source_ref),
    )


def test_conflict_never_returns_arbitrary_current_fact():
    ledger = FactLedger()
    first = _fact(
        value="EUR 1,000,000",
        source_type=FactSourceType.CARRIER_QUOTE,
        source_ref="quote.pdf",
    )
    second = _fact(
        value="EUR 2,000,000",
        source_type=FactSourceType.CARRIER_TOB,
        source_ref="tob.pdf",
    )

    ledger.add(first)
    outcome = ledger.add(second)

    assert outcome.conflict is True
    assert first.fact_id in outcome.conflicting_fact_ids
    assert ledger.current("annual_limit", subject="plan:carrier:executive") is None

    conflicts = ledger.conflicts()
    assert len(conflicts) == 1
    assert conflicts[0].subject == "plan:carrier:executive"
    assert conflicts[0].key == "annual_limit"
    assert set(conflicts[0].fact_ids) == {first.fact_id, second.fact_id}


def test_conflict_requires_explicit_resolution_before_current_value_exists():
    ledger = FactLedger()
    quote_fact = _fact(
        value="EUR 1,000,000",
        source_type=FactSourceType.CARRIER_QUOTE,
        source_ref="quote.pdf",
    )
    tob_fact = _fact(
        value="EUR 2,000,000",
        source_type=FactSourceType.CARRIER_TOB,
        source_ref="tob.pdf",
    )
    ledger.add(quote_fact)
    ledger.add(tob_fact)

    winner = ledger.resolve(
        subject="plan:carrier:executive",
        key="annual_limit",
        winning_fact_id=tob_fact.fact_id,
    )

    assert winner.fact_id == tob_fact.fact_id
    current = ledger.current("annual_limit", subject="plan:carrier:executive")
    assert current is not None
    assert current.fact_id == tob_fact.fact_id
    assert current.value == "EUR 2,000,000"

    all_facts = ledger.for_key(
        "annual_limit",
        subject="plan:carrier:executive",
        include_superseded=True,
    )
    loser = next(fact for fact in all_facts if fact.fact_id == quote_fact.fact_id)
    assert loser.status == FactStatus.SUPERSEDED
