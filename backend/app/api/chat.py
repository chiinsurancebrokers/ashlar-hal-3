from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.agents.orchestrator import get_ashlar_orchestrator

router = APIRouter(prefix="/chat", tags=["chat"])


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    state: dict[str, Any] = {}
    history: list[Message] = []


@router.post("/turn")
async def turn(req: ChatRequest):
    try:
        return await get_ashlar_orchestrator().handle_legacy_chat(
            message=req.message,
            state=req.state,
            history=[m.model_dump() for m in req.history],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HAL conversational service failed: {str(exc)[:180]}")
