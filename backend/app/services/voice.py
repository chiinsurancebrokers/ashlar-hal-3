from __future__ import annotations
import re
import httpx
from num2words import num2words

from backend.app.core.config import get_settings

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"

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


async def _transcribe_via_elevenlabs(file_bytes: bytes, filename: str, content_type: str, language: str | None) -> str:
    settings = get_settings()
    files = {"file": (filename or "audio.webm", file_bytes, content_type or "audio/webm")}
    data = {"model_id": settings.elevenlabs_transcribe_model}
    if language in {"en", "el"}:
        data["language_code"] = language
    headers = {"xi-api-key": settings.elevenlabs_api_key}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(ELEVENLABS_STT_URL, headers=headers, files=files, data=data)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"ElevenLabs transcription failed ({response.status_code}): {(response.text or '')[:200]}")
    text = (response.json() or {}).get("text", "").strip()
    if not text:
        raise RuntimeError("ElevenLabs transcription returned no text.")
    return text


async def _transcribe_via_openai(file_bytes: bytes, filename: str, content_type: str, language: str | None) -> str:
    settings = get_settings()
    files = {"file": (filename or "audio.webm", file_bytes, content_type or "audio/webm")}
    data = {"model": settings.openai_transcribe_model}
    if language in {"en", "el"}:
        data["language"] = language
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(OPENAI_TRANSCRIBE_URL, headers=headers, files=files, data=data)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"OpenAI transcription failed ({response.status_code}): {(response.text or '')[:200]}")
    text = (response.json() or {}).get("text", "").strip()
    if not text:
        raise RuntimeError("OpenAI transcription returned no text.")
    return text


async def transcribe_audio(file_bytes: bytes, filename: str, content_type: str, language: str | None = None) -> str:
    """ElevenLabs Scribe is the primary transcription provider. If it isn't
    configured, or the request fails for any reason (outage, rate limit,
    network error), automatically falls back to OpenAI Whisper — but only
    if that key is actually configured. Both providers get the same
    language pin, since auto-detection on short utterances is unreliable."""
    validate_audio_upload(file_bytes, content_type)
    settings = get_settings()

    if not settings.elevenlabs_api_key and not settings.openai_api_key:
        raise RuntimeError("Voice input is not configured — no transcription provider is available.")

    errors: list[str] = []

    if settings.elevenlabs_api_key:
        try:
            return await _transcribe_via_elevenlabs(file_bytes, filename, content_type, language)
        except Exception as exc:
            errors.append(f"ElevenLabs — {exc}")

    if settings.openai_api_key:
        try:
            return await _transcribe_via_openai(file_bytes, filename, content_type, language)
        except Exception as exc:
            errors.append(f"OpenAI — {exc}")

    raise RuntimeError("Transcription failed on every configured provider: " + " | ".join(errors))


def _parse_spoken_number(raw: str) -> float:
    value = (raw or "").strip().replace("\u00a0", "").replace(" ", "")
    if not value:
        raise ValueError("empty number")
    # When both separators exist, the last separator is the decimal mark.
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        tail = value.rsplit(",", 1)[1]
        value = value.replace(".", "")
        value = value.replace(",", "." if len(tail) in {1, 2} else "")
    elif "." in value:
        tail = value.rsplit(".", 1)[1]
        if len(tail) == 3 and value.count(".") >= 1:
            value = value.replace(".", "")
    return float(value)


_EL_UNITS = {
    0: "μηδέν", 1: "ένα", 2: "δύο", 3: "τρία", 4: "τέσσερα", 5: "πέντε",
    6: "έξι", 7: "επτά", 8: "οκτώ", 9: "εννέα", 10: "δέκα",
    11: "έντεκα", 12: "δώδεκα", 13: "δεκατρία", 14: "δεκατέσσερα",
    15: "δεκαπέντε", 16: "δεκαέξι", 17: "δεκαεπτά", 18: "δεκαοκτώ", 19: "δεκαεννέα",
}
_EL_TENS = {
    20: "είκοσι", 30: "τριάντα", 40: "σαράντα", 50: "πενήντα",
    60: "εξήντα", 70: "εβδομήντα", 80: "ογδόντα", 90: "ενενήντα",
}
_EL_HUNDREDS = {
    100: "εκατό", 200: "διακόσια", 300: "τριακόσια", 400: "τετρακόσια",
    500: "πεντακόσια", 600: "εξακόσια", 700: "επτακόσια", 800: "οκτακόσια", 900: "εννιακόσια",
}


def _greek_integer_words(number: int) -> str:
    if number < 0:
        return "μείον " + _greek_integer_words(-number)
    if number < 20:
        return _EL_UNITS[number]
    if number < 100:
        tens = (number // 10) * 10
        rest = number % 10
        return _EL_TENS[tens] + (f" {_EL_UNITS[rest]}" if rest else "")
    if number < 1000:
        hundreds = (number // 100) * 100
        rest = number % 100
        return _EL_HUNDREDS[hundreds] + (f" {_greek_integer_words(rest)}" if rest else "")
    if number < 1_000_000:
        thousands = number // 1000
        rest = number % 1000
        if thousands == 1:
            prefix = "χίλια"
        else:
            prefix = _greek_integer_words(thousands) + " χιλιάδες"
        return prefix + (f" {_greek_integer_words(rest)}" if rest else "")
    if number < 1_000_000_000:
        millions = number // 1_000_000
        rest = number % 1_000_000
        prefix = "ένα εκατομμύριο" if millions == 1 else _greek_integer_words(millions) + " εκατομμύρια"
        return prefix + (f" {_greek_integer_words(rest)}" if rest else "")
    return str(number)


def _number_words(value: float, language: str) -> str:
    if float(value).is_integer():
        return _greek_integer_words(int(value)) if language == "el" else num2words(int(value), lang="en")
    whole = int(value)
    decimals = round((value - whole) * 100)
    if decimals == 100:
        whole += 1
        decimals = 0
    if language == "el":
        return f"{_greek_integer_words(whole)} και {_greek_integer_words(decimals)}"
    return f"{num2words(whole, lang='en')} point {num2words(decimals, lang='en')}"


def normalize_speech_text(text: str, language: str = "en") -> str:
    """Convert display-oriented numbers into natural speech.

    The visual UI keeps locale-formatted figures such as 2.694,72 €, while
    ElevenLabs receives words, preventing digit-by-digit spelling.
    """
    value = (text or "").strip()
    if not value:
        return value

    currency_names = {
        "el": {
            "EUR": ("ευρώ", "λεπτά"), "€": ("ευρώ", "λεπτά"),
            "USD": ("δολάρια", "σεντ"), "$": ("δολάρια", "σεντ"),
            "GBP": ("λίρες", "πένες"), "£": ("λίρες", "πένες"),
        },
        "en": {
            "EUR": ("euros", "cents"), "€": ("euros", "cents"),
            "USD": ("dollars", "cents"), "$": ("dollars", "cents"),
            "GBP": ("pounds", "pence"), "£": ("pounds", "pence"),
        },
    }

    amount_re = re.compile(
        r"(?:(?P<pre>EUR|USD|GBP|€|\$|£)\s*)?"
        r"(?P<num>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
        r"\s*(?P<post>EUR|USD|GBP|€|\$|£|ευρώ|ευρω|δολάρια|δολαρια|λίρες|λιρες)?",
        re.IGNORECASE,
    )

    def repl_amount(match: re.Match) -> str:
        pre = match.group("pre")
        post = match.group("post")
        token = pre or post
        if not token:
            return match.group(0)
        token_key = token.upper() if token.upper() in {"EUR", "USD", "GBP"} else token
        if token_key in {"ευρώ", "ευρω"}:
            token_key = "EUR"
        elif token_key in {"δολάρια", "δολαρια"}:
            token_key = "USD"
        elif token_key in {"λίρες", "λιρες"}:
            token_key = "GBP"
        try:
            amount = _parse_spoken_number(match.group("num"))
        except ValueError:
            return match.group(0)
        whole = int(amount)
        cents = round((amount - whole) * 100)
        major, minor = currency_names[language].get(token_key, currency_names[language]["EUR"])
        whole_words = _greek_integer_words(whole) if language == "el" else num2words(whole, lang="en")
        words = f"{whole_words} {major}"
        if cents:
            connector = " και " if language == "el" else " and "
            cent_words = _greek_integer_words(cents) if language == "el" else num2words(cents, lang="en")
            words += connector + f"{cent_words} {minor}"
        return words

    value = amount_re.sub(repl_amount, value)

    pct_re = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)\s*%")
    def repl_pct(match: re.Match) -> str:
        try:
            number = _parse_spoken_number(match.group("num"))
        except ValueError:
            return match.group(0)
        words = _number_words(number, language)
        return f"{words} τοις εκατό" if language == "el" else f"{words} percent"
    value = pct_re.sub(repl_pct, value)

    # Remaining standalone large numbers are spoken as cardinal numbers.
    standalone_re = re.compile(r"(?<![\w/])\d{3,}(?:[.,]\d{3})*(?![\w/])")
    def repl_number(match: re.Match) -> str:
        try:
            number = _parse_spoken_number(match.group(0))
            return _greek_integer_words(int(number)) if language == "el" else num2words(int(number), lang="en")
        except Exception:
            return match.group(0)
    value = standalone_re.sub(repl_number, value)
    return value


def pick_voice_id(language: str) -> str | None:
    """Pick a usable multilingual ElevenLabs voice.

    Greek must never go silent merely because a Greek-specific voice was not
    configured. eleven_multilingual_v2 can speak Greek using the configured
    default/English library voice, so fall back in that order.
    """
    settings = get_settings()
    if language == "el":
        return (
            settings.elevenlabs_voice_id_el
            or settings.elevenlabs_voice_id
            or settings.elevenlabs_voice_id_en
        )
    if language == "en":
        return settings.elevenlabs_voice_id_en or settings.elevenlabs_voice_id
    return settings.elevenlabs_voice_id or settings.elevenlabs_voice_id_en


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
    clean_text = normalize_speech_text(clean_text, language)

    headers = {"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    body = {"text": clean_text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(ELEVENLABS_TTS_URL.format(voice_id=voice_id), headers=headers, json=body)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Speech synthesis failed ({response.status_code}): {(response.text or '')[:200]}")
    return response.content
