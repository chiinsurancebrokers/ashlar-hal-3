from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.app.services.voice import transcribe_audio, synthesize_speech

router = APIRouter(tags=["voice"])


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str | None = Form(None)):
    try:
        data = await file.read()
        text = await transcribe_audio(data, file.filename or "audio.webm", file.content_type or "", language)
        return {"text": text}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {str(exc)[:180]}") from exc


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="en", pattern="^(en|el)$")


@router.post("/speak")
async def speak(req: SpeakRequest):
    try:
        audio = await synthesize_speech(req.text, req.language)
        return Response(content=audio, media_type="audio/mpeg")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Speech synthesis failed: {str(exc)[:180]}") from exc
