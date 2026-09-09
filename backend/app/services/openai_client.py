from __future__ import annotations
from typing import Any
import httpx

from backend.app.core.config import get_settings

RESPONSES_URL = "https://api.openai.com/v1/responses"


def build_history_input(history: list[dict] | None, message: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            items.append({"role": role, "content": content[:4000]})
    items.append({"role": "user", "content": (message or "")[:8000]})
    return items


def extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                text = part.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)
    return "".join(chunks).strip()


def build_request_body(*, instructions: str, message: str, history: list[dict] | None,
                        json_mode: bool, max_output_tokens: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    body: dict[str, Any] = {
        "model": settings.openai_chat_model,
        "instructions": instructions,
        "input": build_history_input(history, message),
        "store": False,  # HAL never stores applicant conversations with OpenAI.
        "max_output_tokens": max_output_tokens or settings.openai_chat_max_output_tokens,
    }
    if json_mode:
        body["text"] = {"format": {"type": "json_object"}}
    return body


async def adviser_response(*, instructions: str, message: str, history: list[dict] | None = None,
                            json_mode: bool = False, max_output_tokens: int | None = None) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    body = build_request_body(instructions=instructions, message=message, history=history,
                               json_mode=json_mode, max_output_tokens=max_output_tokens)
    headers = {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=settings.openai_chat_timeout_seconds) as client:
        response = await client.post(RESPONSES_URL, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()

    text = extract_output_text(payload)
    if not text:
        raise RuntimeError("OpenAI returned no text output.")
    return text
