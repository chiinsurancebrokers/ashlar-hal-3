from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


def _html() -> str:
    return FRONTEND.read_text(encoding="utf-8")


def test_bilingual_ui_dictionary_has_core_end_to_end_surfaces():
    html = _html()
    for token in [
        "Κατανόηση αναγκών",
        "Σύγκριση προγραμμάτων",
        "Αίτημα πρότασης",
        "Απαλλαγή",
        "Ιατρική διακομιδή",
        "Αποστολή αιτήματος",
        "Φωνή ενεργή",
        "Από την αρχή",
        "Δεν έχει επιβεβαιωθεί",
    ]:
        assert token in html


def test_quote_card_chrome_uses_translation_keys_not_fixed_english():
    html = _html()
    assert "${t('coverage')}" in html
    assert "${t('deductible')}" in html
    assert "${t('evacuation')}" in html
    assert "${t('getProposal')}" in html
    assert "${t('tellMore')}" in html
    assert "${t('recommended')}" in html


def test_language_toggle_and_browser_greek_detection_are_present():
    html = _html()
    assert "setUiLanguage('en')" in html
    assert "setUiLanguage('el')" in html
    assert "navigator.language" in html
    assert "startsWith('el')" in html


def test_localized_validation_and_voice_status_use_dictionary():
    html = _html()
    for expression in [
        "t('fillNameEmail')",
        "t('confirmConsent')",
        "t('sending')",
        "t('recording')",
        "t('transcribing')",
        "t('transcriptionReady')",
        "t('micDenied')",
    ]:
        assert expression in html