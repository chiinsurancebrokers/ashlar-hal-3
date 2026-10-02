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
    assert "t('recommended')" in html


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

def test_plan_documents_render_as_clickable_pdf_cards_not_raw_urls():
    html = _html()
    assert 'class="plan-doc-link"' in html
    assert "target=\"_blank\"" in html
    assert "rel=\"noopener noreferrer\"" in html
    assert "openPdf" in html
    assert "Table of Benefits" in html
    assert "Πίνακας Παροχών" in html


def test_chat_messages_wrap_long_content_instead_of_forcing_horizontal_overflow():
    html = _html()
    assert "overflow-wrap:anywhere" in html
