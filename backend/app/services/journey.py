from __future__ import annotations

TRAVEL_TERMS = [
    "travel insurance", "travel plan", "trip insurance", "holiday insurance", "single trip",
    "annual multi trip", "annual multi-trip", "travelling for", "traveling for", "vacation",
    "business trip", "ταξιδιωτικ", "ταξίδι", "ταξιδι", "διακοπές", "διακοπες",
]
LOCAL_TERMS = [
    "local insurance", "local health", "domestic insurance", "greek health insurance",
    "ασφάλιση υγείας στην ελλάδα", "ασφαλιση υγειας στην ελλαδα", "τοπική ασφάλιση", "τοπικη ασφαλιση",
    "μόνο ελλάδα", "μονο ελλαδα",
]
IPMI_TERMS = [
    "international health", "international medical", "ipmi", "global health", "worldwide cover",
    "worldwide insurance", "expat health", "international insurance", "διεθνή ασφάλιση", "διεθνη ασφαλιση",
    "treatment abroad", "cover abroad", "comprehensive", "hnwi", "affluent",
]


def classify_journey(message: str, state: dict | None = None) -> str:
    text = (message or "").lower()
    state = state or {}

    if any(x in text for x in TRAVEL_TERMS):
        return "travel"
    if any(x in text for x in LOCAL_TERMS):
        return "local_review"
    if any(x in text for x in IPMI_TERMS):
        return "ipmi"

    if any([
        state.get("cross_border_treatment_required"), state.get("continuity_portability_required"),
        state.get("high_annual_limit_required"), state.get("home_country_treatment_required"),
        state.get("client_segment") in {"hnwi", "affluent", "international", "expat"},
    ]):
        return "ipmi"

    return str(state.get("journey") or "undetermined")
