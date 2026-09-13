from __future__ import annotations
from typing import Any
import httpx

from backend.app.core.config import get_settings

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def build_messages(history: list[dict] | None, message: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": (message or "")[:8000]})
    # The Messages API requires the turn sequence to start with "user" and
    # alternate — if trimmed history left it starting on "assistant", drop
    # the leading assistant turns rather than send an invalid request.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def extract_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for block in payload.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                chunks.append(text)
    return "".join(chunks).strip()


def build_request_body(*, instructions: str, message: str, history: list[dict] | None,
                        json_mode: bool = False, max_tokens: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    system = instructions
    if json_mode:
        system += "\n\nRespond with a single valid JSON object only — no prose, no markdown fences, nothing before or after the JSON."
    body: dict[str, Any] = {
        "model": settings.anthropic_chat_model,
        "system": system,
        "messages": build_messages(history, message),
        "max_tokens": max_tokens or settings.anthropic_chat_max_tokens,
    }
    return body


async def claude_response(*, instructions: str, message: str, history: list[dict] | None = None,
                           json_mode: bool = False, max_tokens: int | None = None) -> str:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

    body = build_request_body(instructions=instructions, message=message, history=history,
                               json_mode=json_mode, max_tokens=max_tokens)
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=settings.anthropic_chat_timeout_seconds) as client:
        response = await client.post(MESSAGES_URL, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()

    text = extract_text(payload)
    if not text:
        raise RuntimeError("Claude returned no text output.")
    return text
