"""Which countries of residence HAL can price, and for which area of cover.

Source: Morgan Price "Evolution Health Policy EU" policy wording (04/26):
* Section 2a "Who can apply?": international policy for expatriates and local
  nationals "with the exception of the United States of America"; not
  available "where it would breach any sanction, or where it is prohibited
  by law or local legislation" (sanctions clause 8p).
* Section 5 "Geographical area": Area 1 = the European countries listed
  below; Area 2 = worldwide excluding China, Hong Kong, Singapore and USA;
  Area 3 = worldwide excluding USA; Area 4 = worldwide.

HAL rule (not an insurer rule): the area of cover must include the country
where the client lives, otherwise the plan would not cover them at home.

As of 13 Oct 2026, the only official rate workbook loaded is Morgan Price
2026. Legacy APRIL / IMG rate tables (Greek-residents-only) were withdrawn
from online quoting pending the receipt of 2026 workbooks from those
carriers — see the comment on OFFICIAL_FILE in registry.py.
"""
from __future__ import annotations

import unicodedata

_EUROPE = {
    "albania", "andorra", "austria", "belarus", "belgium", "bosnia and herzegovina", "bosnia herzegovina", "bulgaria",
    "channel islands", "jersey", "guernsey", "croatia", "cyprus", "czechia", "czech republic", "denmark", "estonia",
    "finland", "france", "germany", "gibraltar", "greece", "greenland", "hungary", "iceland", "ireland", "isle of man",
    "italy", "latvia", "liechtenstein", "lithuania", "luxembourg", "north macedonia", "macedonia", "madeira", "malta",
    "moldova", "monaco", "montenegro", "netherlands", "norway", "poland", "portugal", "romania", "russia", "serbia",
    "slovakia", "slovenia", "spain", "sweden", "switzerland", "turkiye", "turkey", "ukraine", "united kingdom",
    "vatican", "vatican city", "san marino", "kosovo",
}
_USA = {"united states", "united states of america", "usa", "us", "america"}
_AREA2_EXCLUDED = _USA | {"china", "hong kong", "singapore"}
# Countries where cover would likely breach sanctions: never priced online,
# an adviser checks with the insurer.
_SANCTIONS_REVIEW = {"russia", "belarus", "iran", "north korea", "syria", "cuba", "crimea"}
_GREECE = {"greece", "gr", "hellas", "ελλαδα", "ellada"}


def _key(country: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(country or "")).encode("ascii", "ignore").decode() or str(country or "")
    return " ".join(text.lower().replace("&", "and").split())


def residence_status(country: str | None) -> str:
    """'priced', 'us_resident', 'sanctions_review' or 'unknown'."""
    key = _key(country)
    if not key:
        return "unknown"
    if key in _USA:
        return "us_resident"
    if key in _SANCTIONS_REVIEW:
        return "sanctions_review"
    return "priced"


def is_greek_resident(country: str | None) -> bool:
    return _key(country) in _GREECE or str(country or "").strip().lower() in {"ελλάδα"}


def in_europe(country: str | None) -> bool:
    return _key(country) in _EUROPE


def area_includes(area: str | None, country: str | None) -> bool:
    key = _key(country)
    if area == "area1":
        return key in _EUROPE
    if area == "area2":
        return key not in _AREA2_EXCLUDED
    if area == "area3":
        return key not in _USA
    return area == "area4"
