import hmac
import html

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from backend.app.core.config import get_settings
from backend.app.services.followups import process_due, unsubscribe

router = APIRouter(prefix="/followups", tags=["followups"])

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Ashlar Assurance</title></head>
<body style="font-family:Arial,sans-serif;background:#f6f7f9;color:#172333;margin:0;padding:48px 16px">
<div style="max-width:520px;margin:auto;background:#fff;border-radius:14px;padding:28px;box-shadow:0 1px 4px rgba(0,0,0,.08)">
<h2 style="margin-top:0">{title_en}</h2><p>{body_en}</p><hr style="border:none;border-top:1px solid #e3e6ea;margin:20px 0">
<h2>{title_el}</h2><p>{body_el}</p><p style="color:#687586;font-size:13px;margin-top:24px">Ashlar Assurance</p></div></body></html>"""


def _page(ok: bool) -> HTMLResponse:
    if ok:
        texts = dict(title_en="You will not receive more reminders",
                     body_en="We have stopped the reminder emails for this quote. Your saved quote stays available until it expires.",
                     title_el="Δεν θα λάβετε άλλες υπενθυμίσεις",
                     body_el="Σταματήσαμε τις υπενθυμίσεις για αυτή την προσφορά. Η αποθηκευμένη προσφορά σας παραμένει διαθέσιμη μέχρι να λήξει.")
    else:
        texts = dict(title_en="This link is not valid",
                     body_en="Please reply to any of our emails and we will stop the reminders for you.",
                     title_el="Ο σύνδεσμος δεν είναι έγκυρος",
                     body_el="Απαντήστε σε οποιοδήποτε email μας και θα σταματήσουμε τις υπενθυμίσεις.")
    return HTMLResponse(_PAGE.format(**{k: html.escape(v) for k, v in texts.items()}),
                        status_code=200 if ok else 400,
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"})


@router.get("/unsubscribe", include_in_schema=False)
@router.post("/unsubscribe", include_in_schema=False)  # one-click (List-Unsubscribe-Post)
def unsubscribe_link(ref: str = Query(max_length=40), t: str = Query(max_length=64)):
    try:
        ok = unsubscribe(ref, t)
    except Exception:
        ok = False
    return _page(ok)


@router.post("/run", include_in_schema=False)
async def run_now(x_followup_token: str = Header(default="")):
    """Send whatever is due right now (admin / testing)."""
    token = get_settings().followup_admin_token
    if not token or not hmac.compare_digest(token, x_followup_token):
        raise HTTPException(status_code=404, detail="Not found")
    return await process_due()
