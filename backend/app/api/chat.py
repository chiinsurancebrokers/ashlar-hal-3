from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.services.orchestrator import chat_turn

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
        return await chat_turn(req.message, req.state, [m.model_dump() for m in req.history])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HAL conversational service failed: {str(exc)[:180]}")
