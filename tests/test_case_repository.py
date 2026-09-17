from backend.app.cases.models import AshlarCase, CaseClient
from backend.app.cases.repository import InMemoryCaseRepository


def test_case_repository_roundtrip():
    repo = InMemoryCaseRepository()
    case = AshlarCase(client=CaseClient(display_name="Repository Test"))

    saved = repo.save(case)
    loaded = repo.get(case.case_id)

    assert saved.case_id == case.case_id
    assert loaded is not None
    assert loaded.client.display_name == "Repository Test"


def test_case_repository_returns_none_for_unknown_case():
    repo = InMemoryCaseRepository()
    assert repo.get("missing-case") is None
