from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import Fact, FactSource, FactSourceType, FactStatus


def _fact(value, *, status=FactStatus.VERIFIED, source_type=FactSourceType.CARRIER_TOB):
    return Fact(
        subject="plan:cigna:executive",
        key="annual_limit",
        value=value,
        currency="EUR",
        provider="Cigna",
        plan_key="cigna:executive",
        status=status,
        source=FactSource(source_type=source_type, source_ref="test fixture"),
    )


def test_same_fact_from_multiple_sources_is_not_a_conflict():
    ledger = FactLedger()
    ledger.add(_fact(2_000_000))
    result = ledger.add(_fact(2_000_000, status=FactStatus.EXTRACTED))

    assert result.conflict is False
    assert ledger.conflicts() == []
    assert ledger.current("annual_limit", "plan:cigna:executive").value == 2_000_000


def test_conflicting_carrier_facts_are_never_silently_resolved():
    ledger = FactLedger()
    first = ledger.add(_fact(2_000_000)).fact
    second = ledger.add(_fact(1_500_000)).fact

    assert first.fact_id != second.fact_id
    assert ledger.current("annual_limit", "plan:cigna:executive") is None
    conflicts = ledger.conflicts()
    assert len(conflicts) == 1
    assert set(conflicts[0].fact_ids) == {first.fact_id, second.fact_id}


def test_explicit_resolution_supersedes_other_active_facts():
    ledger = FactLedger()
    old = ledger.add(_fact(2_000_000)).fact
    actual_quote = ledger.add(_fact(1_500_000)).fact

    ledger.resolve(
        subject="plan:cigna:executive",
        key="annual_limit",
        winning_fact_id=actual_quote.fact_id,
    )

    assert ledger.current("annual_limit", "plan:cigna:executive").fact_id == actual_quote.fact_id
    old_after = next(f for f in ledger.facts if f.fact_id == old.fact_id)
    assert old_after.status == FactStatus.SUPERSEDED
