import pytest

from backend.app.services.voice import validate_audio_upload, pick_voice_id
from backend.app.core.config import Settings


def test_validate_audio_rejects_empty():
    with pytest.raises(ValueError, match="No audio"):
        validate_audio_upload(b"", "audio/webm")


def test_validate_audio_rejects_oversized(monkeypatch):
    from backend.app.core import config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("MAX_AUDIO_UPLOAD_MB", "1")
    config_module.get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="too large"):
            validate_audio_upload(b"x" * (2 * 1024 * 1024), "audio/webm")
    finally:
        monkeypatch.delenv("MAX_AUDIO_UPLOAD_MB", raising=False)
        config_module.get_settings.cache_clear()


def test_validate_audio_rejects_unsupported_content_type():
    with pytest.raises(ValueError, match="Unsupported audio format"):
        validate_audio_upload(b"some bytes", "application/pdf")


def test_validate_audio_accepts_supported_types():
    validate_audio_upload(b"some bytes", "audio/webm")
    validate_audio_upload(b"some bytes", "audio/mpeg")
    validate_audio_upload(b"some bytes", None)  # missing content-type is tolerated, not rejected


def test_validate_audio_accepts_real_browser_codec_suffixed_types():
    # Regression: real browsers report MediaRecorder's actual mimeType,
    # which includes codec parameters (e.g. Chrome sends
    # "audio/webm;codecs=opus") — every real recording was being rejected
    # as an 'unsupported format' because this never exact-matched the
    # allowlist. This is the live 400 error that was reported.
    validate_audio_upload(b"some bytes", "audio/webm;codecs=opus")
    validate_audio_upload(b"some bytes", "audio/ogg;codecs=opus")
    validate_audio_upload(b"some bytes", "AUDIO/WEBM;codecs=opus")  # case-insensitive too


def test_pick_voice_id_prefers_language_specific_voice(monkeypatch):
    from backend.app.core import config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "default_voice")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_EL", "greek_voice")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_EN", "english_voice")
    config_module.get_settings.cache_clear()
    try:
        assert pick_voice_id("el") == "greek_voice"
        assert pick_voice_id("en") == "english_voice"
    finally:
        for k in ["ELEVENLABS_VOICE_ID", "ELEVENLABS_VOICE_ID_EL", "ELEVENLABS_VOICE_ID_EN"]:
            monkeypatch.delenv(k, raising=False)
        config_module.get_settings.cache_clear()


def test_pick_voice_id_falls_back_to_default_when_language_specific_missing(monkeypatch):
    from backend.app.core import config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "default_voice")
    config_module.get_settings.cache_clear()
    try:
        assert pick_voice_id("el") == "default_voice"
    finally:
        monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
        config_module.get_settings.cache_clear()
