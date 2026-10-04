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

def test_plan_documents_render_inside_embedded_ashlar_viewer():
    html = _html()
    assert 'class="plan-doc-link"' in html
    assert "openSourceViewer(" in html
    assert 'id="sourceViewerModal"' in html
    assert 'id="sourceViewerFrame"' in html
    assert "target=\"_blank\"" not in html
    assert "Table of Benefits" in html
    assert "Πίνακας Παροχών" in html


def test_chat_messages_wrap_long_content_instead_of_forcing_horizontal_overflow():
    html = _html()
    assert "overflow-wrap:anywhere" in html


def test_voice_controller_stops_previous_audio_and_tts_request():
    html = _html()
    assert "let activeSpeechAudio = null" in html
    assert "let activeSpeechController = null" in html
    assert "function stopSpeech()" in html
    assert "activeSpeechAudio.pause()" in html
    assert "activeSpeechController.abort()" in html
    assert "stopSpeech();\n  document.getElementById('input').value" in html


def test_plan_cards_keep_readable_minimum_width_instead_of_three_squeezed_columns():
    html = _html()
    assert "grid-auto-columns:minmax(300px,340px)" in html
    assert "@media(min-width:900px)" in html
    assert "word-break:normal" in html


def test_current_policy_upload_is_bilingual_and_server_proxied():
    html = _html()
    assert "Compare with your current policy" in html
    assert "Σύγκρινε με το τρέχον συμβόλαιό σου" in html
    assert "API+'/quotes/current-policy'" in html
    assert "let currentPolicy = null" in html
    assert "currentPolicyBenefitForRow" in html
    assert "benefit_rows" in html


def test_quote_cards_never_switch_to_squeezed_three_column_layout():
    html = _html()
    assert "@media(min-width:1180px){.quotes-row" not in html
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" not in html
    assert "grid-auto-columns:minmax(300px,340px)" in html


def test_current_policy_email_sends_signed_token_not_browser_policy_object():
    html = _html()
    assert "let currentPolicyToken = null" in html
    assert "currentPolicyToken=d.current_policy_token||null" in html
    assert "current_policy_token:currentPolicyToken" in html


def test_primary_healthcare_country_and_context_are_exposed_in_ui():
    html = _html()
    assert "primary_healthcare_country" in html
    assert "Main healthcare country" in html
    assert "Κύρια χώρα περίθαλψης" in html
    assert "renderHealthcareContext" in html
    assert "API+'/healthcare/context" in html or "/healthcare/context?country=" in html


def test_current_policy_supporting_documents_use_embedded_viewer():
    html = _html()
    assert "supporting_documents" in html
    assert "policy_wording_status" in html
    assert "policyWordings" in html
    assert "policyWordingMissing" in html


def test_comparison_email_prefills_real_applicant_name_and_preserves_error_detail():
    html = _html()
    assert "state.applicant_name||''" in html
    assert 'autocomplete="name"' in html
    assert 'autocomplete="email"' in html
    assert "invalid_grant" in html
    assert "needs to be re-authorized" in html


def test_frontend_does_not_contain_invalid_escaped_quote_expression():
    html = _html()
    assert "esc(t(\\'currentEuropesure\\'))" not in html
    assert "esc(t('currentEuropesure'))" in html
