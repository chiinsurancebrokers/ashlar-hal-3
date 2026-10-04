from __future__ import annotations

from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "healthcare"


def _slug(country: str) -> str:
    value = (country or "").strip().casefold()
    aliases = {
        "ελλάδα": "greece", "ελλαδα": "greece", "hellas": "greece",
        "united kingdom": "united-kingdom", "uk": "united-kingdom",
        "united states": "united-states", "usa": "united-states",
    }
    value = aliases.get(value, value)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def _parse_profile(path: Path) -> dict:
    profile: dict = {"metrics": [], "sources": []}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key == "metric":
            parts = [x.strip() for x in value.split("|", 4)]
            if len(parts) == 5:
                metric_key, country_value, comparator_value, label_en, label_el = parts
                profile["metrics"].append({
                    "key": metric_key,
                    "country_value": country_value,
                    "comparator_value": comparator_value,
                    "label_en": label_en,
                    "label_el": label_el,
                })
        elif key == "source":
            parts = [x.strip() for x in value.split("|", 1)]
            if len(parts) == 2:
                profile["sources"].append({"label": parts[0], "url": parts[1]})
        else:
            profile[key] = value
    return profile


def healthcare_context(country: str, language: str = "en") -> dict:
    slug = _slug(country)
    path = DATA_DIR / f"{slug}.txt"
    if not path.exists():
        return {
            "available": False,
            "country": country,
            "title": (
                f"Healthcare context: {country}" if language != "el"
                else f"Πλαίσιο περίθαλψης: {country}"
            ),
            "message": (
                "A curated country profile is not available yet. HAL will still use your answer for future country-specific analysis."
                if language != "el"
                else "Δεν υπάρχει ακόμη επιμελημένο προφίλ για αυτή τη χώρα. Ο HAL θα διατηρήσει την απάντησή σας για μελλοντική ανάλυση ανά χώρα."
            ),
            "metrics": [],
            "sources": [],
        }

    data = _parse_profile(path)
    greek = language == "el"
    return {
        "available": True,
        "country": data.get("country") or country,
        "updated": data.get("updated"),
        "title": data.get("title_el" if greek else "title_en"),
        "intro": data.get("intro_el" if greek else "intro_en"),
        "balanced": data.get("balanced_el" if greek else "balanced_en"),
        "metrics": [
            {
                "key": m["key"],
                "country_value": m["country_value"],
                "comparator_value": m["comparator_value"],
                "label": m["label_el" if greek else "label_en"],
            }
            for m in data.get("metrics", [])
        ],
        "sources": data.get("sources", []),
    }


