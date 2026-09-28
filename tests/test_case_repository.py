from backend.app.cases.models import AshlarCase, CaseStatus
from backend.app.cases.repository import InMemoryCaseRepository


def test_repository_requires_explicit_save_and_returns_copies():
    repo = InMemoryCaseRepository()
    created = repo.create(AshlarCase())

    fetched = repo.get(created.case_id)
    fetched.status = CaseStatus.COMPARISON

    # Stored object is unchanged until save() is called.
    assert repo.get(created.case_id).status == CaseStatus.DISCOVERY

    saved = repo.save(fetched)
    assert saved.status == CaseStatus.COMPARISON
    assert repo.get(created.case_id).status == CaseStatus.COMPARISON
