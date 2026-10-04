"""Serve official carrier PDFs from HAL's own origin.

Some carriers (e.g. morgan-price.eu) forbid their PDFs from being shown inside
another site's iframe, so the in-HAL document viewer shows "refused to
connect". HAL fetches the PDF server-side and serves it inline from its own
domain instead.

Security: this is NOT an open proxy. Only URLs registered in HAL's evidence
manifests are accepted (exact match); anything else returns 404.
"""
from __future__ import annotations

import time
from functools import lru_cache

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.app.evidence.morgan_price_2026 import load_manifest

router = APIRouter(prefix="/documents", tags=["documents"])

_MAX_BYTES = 25 * 1024 * 1024
_CACHE_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, bytes]] = {}


@lru_cache
def _allowed_documents() -> dict[str, str]:
    """Map of allowed official URL -> filename."""
    allowed: dict[str, str] = {}
    for doc in load_manifest().get("documents", []):
        url = str(doc.get("official_url") or "")
        if url.startswith("https://"):
            allowed[url] = url.rsplit("/", 1)[-1] or "document.pdf"
    return allowed


async def _fetch(url: str) -> bytes:
    cached = _cache.get(url)
    if cached and time.time() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Ashlar HAL document viewer)"})
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="The insurer's document could not be retrieved right now.")
    content = response.content
    if len(content) > _MAX_BYTES or not content.startswith(b"%PDF"):
        raise HTTPException(status_code=502, detail="The insurer returned an unexpected document.")
    _cache[url] = (time.time(), content)
    return content


@router.get("/view")
async def view_document(url: str = Query(..., max_length=500)):
    filename = _allowed_documents().get(url)
    if not filename:
        raise HTTPException(status_code=404, detail="Document is not available in HAL.")
    try:
        content = await _fetch(url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="The insurer's document could not be retrieved right now.") from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )
