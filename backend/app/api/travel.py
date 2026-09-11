from fastapi import APIRouter

from backend.app.travel.europesure import public_catalog

router = APIRouter(prefix="/travel", tags=["travel"])


@router.get("/europesure")
async def europesure_catalog():
    return public_catalog()
