from __future__ import annotations
import httpx

from backend.app.core.config import get_settings

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/mp3",
}


def validate_audio_upload(file_bytes: bytes, content_type: str | None) -> None:
    """Pure validation — no network call, fully testable. Raises ValueError
    with a client-safe message on any problem."""
    settings = get_settings()
    if not file_bytes:
        raise ValueError("No audio data received.")
    max_bytes = settings.max_audio_upload_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(f"Audio file is too large (max {settings.max_audio_upload_mb}MB).")
    # Real browsers report MediaRecorder's mimeType WITH codec parameters,
    # e.g. "audio/webm;codecs=opus" on Chrome — strip that before checking,
    # or every real recording gets rejected as an 'unsupported format'.
    base_type = (content_type or "").split(";")[0].strip().lower()
    if base_type and base_type not in ALLOWED_AUDIO_CONTENT_TYPES:
        raise ValueError(f"Unsupported audio format: {content_type}")


async def transcribe_audio(file_bytes: bytes, filename: str, content_type: str, language: str | None = None) -> str:
    validate_audio_upload(file_bytes, content_type)
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured — voice input is unavailable.")

    files = {"file": (filename or "audio.webm", file_bytes, content_type or "audio/webm")}
    data = {"model_id": settings.elevenlabs_transcribe_model}
    # Language auto-detection on short utterances is unreliable (e.g.
    # "Greece" came back transcribed in the wrong language entirely) — pin
    # it explicitly whenever the caller knows which of our two supported
    # languages is active.
    if language in {"en", "el"}:
        data["language_code"] = language
    headers = {"xi-api-key": settings.elevenlabs_api_key}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(ELEVENLABS_STT_URL, headers=headers, files=files, data=data)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Transcription failed ({response.status_code}): {(response.text or '')[:200]}")

    text = (response.json() or {}).get("text", "").strip()
    if not text:
        raise RuntimeError("Transcription returned no text — please try speaking again.")
    return text


def pick_voice_id(language: str) -> str | None:
    """Pure function, testable without network."""
    settings = get_settings()
    if language == "el" and settings.elevenlabs_voice_id_el:
        return settings.elevenlabs_voice_id_el
    if language == "en" and settings.elevenlabs_voice_id_en:
        return settings.elevenlabs_voice_id_en
    return settings.elevenlabs_voice_id


async def synthesize_speech(text: str, language: str = "en") -> bytes:
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured — voice output is unavailable.")
    voice_id = pick_voice_id(language)
    if not voice_id:
        raise RuntimeError("No ElevenLabs voice_id is configured for this language.")

    clean_text = (text or "").strip()[:2000]
    if not clean_text:
        raise ValueError("No text provided to speak.")

    headers = {"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    body = {"text": clean_text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(ELEVENLABS_TTS_URL.format(voice_id=voice_id), headers=headers, json=body)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Speech synthesis failed ({response.status_code}): {(response.text or '')[:200]}")
    return response.content
