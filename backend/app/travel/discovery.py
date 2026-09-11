from __future__ import annotations
import re

from backend.app.travel.europesure import destination_scope, looks_like_long_stay

SKIP = {"skip", "not sure", "no preference", "i don't know", "i dont know", "pass",
        "δεν ξέρω", "δεν ξερω", "παράλειψη", "παραλειψη"}


def _clean(text: str, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


def _is_skip(text: str) -> bool:
    return _clean(text).lower() in SKIP


def _looks_like_place(text: str) -> bool:
    """Rejects transcription noise / non-place input (e.g. '>>>>>>>>') before
    it is ever treated as a verified-sounding fact HAL echoes back."""
    t = _clean(text)
    if len(t) < 2 or len(t) > 70:
        return False
    letters = sum(1 for c in t if c.isalpha())
    if letters < max(2, int(len(t) * 0.6)):
        return False
    return bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿΑ-Ωα-ωΆ-ώ .,'-]+", t))


def deterministic_travel_updates(message: str, state: dict) -> dict:
    pending = state.get("travel_pending_question")
    text = _clean(message)
    out: dict = {}

    if pending and _is_skip(text):
        defaults = {
            "trip_type": {"travel_trip_type": "single", "trip_type_answered": True},
            "cover_preference": {"travel_cover_preference": "balanced", "cover_preference_answered": True},
            # destination and age have no safe default — skip re-asks them.
        }
        result = dict(defaults.get(pending, {}))
        if result:
            result["travel_pending_question"] = None
        return result

    if pending == "trip_type":
        low = text.lower()
        if any(x in low for x in ["single", "one trip", "μονό", "μονο ταξιδι"]):
            out.update(travel_trip_type="single", trip_type_answered=True)
        elif any(x in low for x in ["annual", "multi", "multi-trip", "multi trip", "ετήσιο", "ετησιο"]):
            out.update(travel_trip_type="annual", trip_type_answered=True)

    elif pending == "destination":
        if _looks_like_place(text):
            out["travel_destination"] = text
            out["travel_destination_scope"] = destination_scope(text)
            if looks_like_long_stay(message) and not state.get("travel_long_stay_warning_shown"):
                out["travel_long_stay_flag"] = True

    elif pending == "age":
        m = re.search(r"\b(\d{1,3})\b", text)
        if m:
            age = int(m.group(1))
            if 0 <= age <= 120:
                out["travel_age"] = age

    elif pending == "cover_preference":
        low = text.lower()
        if any(x in low for x in ["budget", "cheap", "economy", "basic", "φθην"]):
            out.update(travel_cover_preference="budget", cover_preference_answered=True)
        elif any(x in low for x in ["highest", "maximum", "premium", "strongest", "μέγιστ", "μεγιστ"]):
            out.update(travel_cover_preference="highest", cover_preference_answered=True)
        elif any(x in low for x in ["balanced", "balance", "value", "ισορροπ"]):
            out.update(travel_cover_preference="balanced", cover_preference_answered=True)

    if out and pending and any(k.endswith("_answered") or k.startswith("travel_") for k in out):
        out["travel_pending_question"] = None
    return out


def next_travel_question(state: dict) -> dict | None:
    if not state.get("trip_type_answered"):
        return {"key": "trip_type", "reply": "Do you need cover for one trip or annual multi-trip cover?",
                "quick_replies": [{"label": "Single trip", "value": "single trip"}, {"label": "Annual multi-trip", "value": "annual multi-trip"}]}
    if not state.get("travel_destination"):
        return {"key": "destination", "reply": "Where are you travelling to?", "quick_replies": []}
    if not state.get("travel_age") and not state.get("age"):
        return {"key": "age", "reply": "How old is the oldest traveller?", "quick_replies": [{"label": "Skip", "value": "skip"}]}
    if not state.get("cover_preference_answered"):
        return {"key": "cover_preference", "reply": "Would you like budget, balanced, or the highest level of cover?",
                "quick_replies": [{"label": "Budget", "value": "budget"}, {"label": "Balanced", "value": "balanced"}, {"label": "Highest cover", "value": "highest"}]}
    return None
