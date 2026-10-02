from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from backend.app.core.config import get_settings


def _secret() -> bytes:
    settings = get_settings()
    value = settings.current_policy_signing_secret or settings.proposal_studio_api_key
    if not value:
        raise RuntimeError("Current-policy signing is not configured.")
    return value.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_current_policy_token(policy: dict, ttl_seconds: int = 21600) -> str:
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + ttl_seconds,
        "policy": policy,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    body = _b64(raw)
    sig = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_current_policy_token(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid current-policy token.") from exc
    expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid current-policy token signature.")
    try:
        payload = json.loads(_unb64(body).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid current-policy token payload.") from exc
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Current-policy token has expired.")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("Current-policy token contains no policy.")
    return policy
