import hmac
from fastapi import HTTPException
from backend.app.core.config import get_settings


def broker_authorized(value):
    if not value:
        return False
    expected = get_settings().admin_password
    if not expected or not hmac.compare_digest(str(value), str(expected)):
        raise HTTPException(403, "Invalid broker credentials.")
    return True
