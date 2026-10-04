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



def _fmt_pct(value: str, greek: bool) -> str:
    return (value.replace(".", ",") if greek else value) + "%"


def healthcare_note(country: str | None, greek: bool = False) -> str:
    """Short, sourced note on the country where the applicant will live,
    shown with the shortlist: why international cover can add value there.

    Built only from the curated profile's verified metrics. Returns "" when
    no curated profile (or a required metric) exists — never improvised.
    """
    if not country:
        return ""
    path = DATA_DIR / f"{_slug(country)}.txt"
    if not path.exists():
        return ""
    data = _parse_profile(path)
    metrics = {m["key"]: m for m in data.get("metrics", [])}
    needed = ("satisfaction", "unmet_needs", "non_mandatory_financing")
    if any(k not in metrics for k in needed):
        return ""
    sat, unmet, oop = (metrics[k] for k in needed)
    p = lambda m, which: _fmt_pct(m[which], greek)  # noqa: E731
    if greek:
        where = data.get("country_in_el") or f"στη χώρα {data.get('country_el') or country}"
        return (
            f"Λίγα λόγια για το σύστημα υγείας {where}: μόνο το {p(sat, 'country_value')} των κατοίκων δηλώνει "
            f"ικανοποιημένο από τη διαθεσιμότητα ποιοτικής περίθαλψης (μέσος όρος ΟΟΣΑ {p(sat, 'comparator_value')}), "
            f"ενώ το {p(unmet, 'country_value')} αναφέρει ανικανοποίητες ανάγκες περίθαλψης λόγω κόστους, απόστασης ή "
            f"αναμονής (ΟΟΣΑ {p(unmet, 'comparator_value')}). Περίπου το {p(oop, 'country_value')} των δαπανών υγείας "
            f"δεν καλύπτεται από το δημόσιο σύστημα (ΟΟΣΑ {p(oop, 'comparator_value')}) και πάνω από το ένα τρίτο "
            "πληρώνεται απευθείας από την τσέπη των νοικοκυριών. Ένα διεθνές πρόγραμμα καλύπτει μεγάλο μέρος αυτών των "
            "εξόδων — ιδιωτική νοσηλεία, εξετάσεις και, ανάλογα με το πρόγραμμα, εξωνοσοκομειακή περίθαλψη — ενώ το "
            "δημόσιο σύστημα παραμένει δίχτυ ασφαλείας. Πηγή: ΟΟΣΑ, Health at a Glance 2025."
        )
    name = data.get("country") or country
    return (
        f"A word on healthcare in {name}: only {p(sat, 'country_value')} of residents are satisfied with the "
        f"availability of quality healthcare (OECD average {p(sat, 'comparator_value')}), and "
        f"{p(unmet, 'country_value')} report unmet healthcare needs because of cost, distance or waiting times "
        f"(OECD {p(unmet, 'comparator_value')}). About {p(oop, 'country_value')} of health spending is not covered by "
        f"the public system (OECD {p(oop, 'comparator_value')}), and more than a third is paid directly out of "
        "households' pockets. International cover pays for much of that — private hospital treatment, diagnostics "
        "and, depending on the plan, outpatient care — while the public system remains a safety net. "
        "Source: OECD, Health at a Glance 2025."
    )
