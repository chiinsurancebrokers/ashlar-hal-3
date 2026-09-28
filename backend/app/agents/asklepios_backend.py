from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import httpx


class AsklepiosServiceError(RuntimeError):
    pass


class AsklepiosHttpBackend:
    """Narrow HTTP adapter from Adviser OS to the independent Asklepios service.

    HAL does not import Kira/Asklepios implementation code. The health service
    owns clinical model calls and returns a small structured contract. Insurance
    coverage is deliberately outside this adapter and remains the responsibility
    of the deterministic PolicyEngine.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = 25.0,
        client: httpx.AsyncClient | None = None,
    ):
        url = str(base_url or "").strip().rstrip("/")
        if not url.startswith(("https://", "http://")):
            raise ValueError("Asklepios base_url must be an absolute HTTP(S) URL")
        self.base_url = url
        self.token = str(token or "").strip() or None
        self.timeout_seconds = float(timeout_seconds)
        self._client = client

    @classmethod
    def from_environment(cls) -> "AsklepiosHttpBackend | None":
        base_url = str(os.getenv("ASKLEPIOS_API_URL") or "").strip()
        if not base_url:
            return None
        timeout = float(os.getenv("ASKLEPIOS_API_TIMEOUT_SECONDS") or "25")
        return cls(
            base_url=base_url,
            token=os.getenv("ASKLEPIOS_API_TOKEN"),
            timeout_seconds=timeout,
        )

    async def handle(
        self,
        *,
        case_id: UUID | None,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        request_body: dict[str, Any] = {
            "case_id": str(case_id) if case_id else None,
            "message": str(message),
            "language": context.get("language"),
            "history": list(context.get("health_history") or []),
        }
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(
                f"{self.base_url}/v1/navigate",
                json=request_body,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AsklepiosServiceError(f"Asklepios service request failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        if not isinstance(payload, dict):
            raise AsklepiosServiceError("Asklepios returned an invalid response")

        reply = payload.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            raise AsklepiosServiceError("Asklepios response is missing a reply")

        result: dict[str, Any] = {"reply": reply.strip()}
        service_key = payload.get("clinical_service_key") or payload.get("benefit_key")
        if isinstance(service_key, str) and service_key.strip():
            result["benefit_key"] = service_key.strip()

        for key in ("urgency", "next_step", "safety_notice", "language"):
            value = payload.get(key)
            if value is not None:
                result[key] = value
        return result
