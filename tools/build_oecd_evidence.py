"""Build per-country OECD evidence files from Health at a Glance 2025.

Usage:
    pdftotext -layout health-at-a-glance-2025.pdf hag.txt
    python tools/build_oecd_evidence.py hag.txt

Writes data/knowledge/oecd_hag2025/<slug>.json for every OECD country, from:
  * Table 1.4 (PDF p.23)  — eligibility, satisfaction, public financing share, unmet needs
  * Figure 5.7 (PDF p.109) — public financing share by type of care
  * Verbatim sentences naming the country in the access, patient-experience
    and expenditure chapters (PDF pp.104-116, 136-140, 160-170)

Only official figures are written; every fact keeps its PDF page.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "knowledge" / "oecd_hag2025"
SOURCE = "OECD (2025), Health at a Glance 2025: OECD Indicators, OECD Publishing, Paris"
TEXT_PAGES = list(range(104, 117)) + list(range(136, 141)) + list(range(160, 171))
TREND = {"+": "improved", "-": "deteriorated", "=": "unchanged"}


def slug(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def num(token: str) -> float | None:
    return None if token in {"N/A", "", None} else float(token.rstrip("%"))


def fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))


def parse_table_14(page: str) -> dict[str, dict]:
    rows = {}
    pattern = re.compile(r"^([A-Z][A-Za-zÇÖÜçöüé .]+?) (\d+|N/A) ([+=\-]|N/A) (\d+|N/A) ([+=\-]|N/A) "
                         r"([\d.]+|N/A) ([+=\-]|N/A) ([\d.]+|N/A) ([+=\-]|N/A)$")
    for line in page.splitlines():
        m = pattern.match(re.sub(r"\s+", " ", line).strip())
        if m:
            name, *v = m.groups()
            rows[name.strip()] = {
                "eligibility": num(v[0]), "eligibility_trend": v[1],
                "satisfaction": num(v[2]), "satisfaction_trend": v[3],
                "public_share": num(v[4]), "public_share_trend": v[5],
                "unmet_needs": num(v[6]), "unmet_needs_trend": v[7],
            }
    return rows


def parse_figure_57(page: str) -> dict[str, dict]:
    rows = {}
    pattern = re.compile(r"^([A-Z][A-Za-zÇÖÜçöüé .]+?)[*¹²]*(?:32)? (\d+%|N/A) (\d+%|N/A) (\d+%|N/A) (\d+%|N/A) (\d+%|N/A)$")
    for line in page.splitlines():
        m = pattern.match(re.sub(r"\s+", " ", line).strip())
        if m:
            name, *v = m.groups()
            name = "OECD" if name.startswith("OECD") else name.strip()
            rows[name] = dict(zip(["all", "hospital", "outpatient", "dental", "pharma"], map(num, v)))
    return rows


def country_sentences(pages: list[str], name: str) -> list[dict]:
    found, seen = [], set()
    for n in TEXT_PAGES:
        text = re.sub(r"\s+", " ", pages[n - 1]).replace("p.p.", "percentage points")
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
            sentence = sentence.strip()
            if re.search(rf"\b{re.escape(name)}\b", sentence) and 40 < len(sentence) < 600 \
                    and not sentence.startswith(("Source", "Note", "StatLink", "1.", "2.", "3.", "OECD/", "OECD (")) \
                    and not re.search(r"doi\.org|Publishing|https?://|\bexclude[sd]?\b|\[\d+\]|comparability", sentence) \
                    and sentence not in seen:
                seen.add(sentence)
                found.append({"page": n, "text": sentence})
    return found


def build(country: str, t14: dict, f57: dict, oecd14: dict, oecd57: dict, sentences: list[dict]) -> dict:
    """Facts are always framed as the GAP (not covered / not satisfied /
    unmet), never as the covered share. Gap figures are the arithmetic
    complement of the published figure (100 - value) and say so."""
    facts, metrics = [], {}
    gap = lambda v: round(100 - v, 1)  # noqa: E731
    if t14:
        if t14["satisfaction"] is not None:
            trend = TREND.get(t14["satisfaction_trend"])
            facts.append({"id": "not_satisfied", "page": 23,
                          "text": f"{fmt(gap(t14['satisfaction']))}% of people in {country} were NOT satisfied with the availability of quality healthcare where they live in 2024, versus an OECD average of {fmt(gap(oecd14['satisfaction']))}%"
                                  + ("; satisfaction has deteriorated over the past decade." if trend == "deteriorated" else ".")})
            metrics["not_satisfied"] = [gap(t14["satisfaction"]), gap(oecd14["satisfaction"])]
        if t14["public_share"] is not None:
            facts.append({"id": "not_public_total", "page": 23,
                          "text": f"{fmt(gap(t14['public_share']))}% of health spending in {country} was NOT covered by government or compulsory insurance schemes in 2023, versus an OECD average of {fmt(gap(oecd14['public_share']))}%."})
            metrics["not_public"] = [gap(t14["public_share"]), gap(oecd14["public_share"])]
        if t14["unmet_needs"] is not None:
            facts.append({"id": "unmet_needs", "page": 23,
                          "text": f"{fmt(t14['unmet_needs'])}% of people in {country} reported unmet medical care needs due to cost, distance or waiting times in 2024 (average of 28 OECD countries: {fmt(oecd14['unmet_needs'])}%)."})
            metrics["unmet_needs"] = [t14["unmet_needs"], oecd14["unmet_needs"]]
    if f57:
        labels = {"hospital": "hospital care", "outpatient": "outpatient medical care",
                  "dental": "dental care", "pharma": "pharmaceutical"}
        for key, label in labels.items():
            if f57.get(key) is not None and oecd57.get(key) is not None:
                facts.append({"id": f"not_public_{key}", "page": 109,
                              "text": f"{fmt(gap(f57[key]))}% of {label} costs in {country} were NOT covered by public or compulsory schemes in 2023, versus {fmt(gap(oecd57[key]))}% on average in the OECD."})
                metrics[f"not_public_{key}"] = [gap(f57[key]), gap(oecd57[key])]
    for i, s in enumerate(sentences, 1):
        facts.append({"id": f"report_text_{i}", "page": s["page"], "text": s["text"], "verbatim": True})
    return {
        "country": country,
        "source": SOURCE,
        "source_short_en": "OECD, Health at a Glance 2025",
        "source_short_el": "ΟΟΣΑ, Health at a Glance 2025",
        "doi": "https://doi.org/10.1787/8f9e3f98-en",
        "framing": "Gap framing: every figure is what is NOT covered, NOT satisfied or unmet. Gap figures are 100 minus the published figure.",
        "rule": "HAL may phrase these facts freely but must not state any figure, ranking or claim that is not in this list. "
                "Verbatim report sentences may name other countries; only what they say about this country may be used.",
        "metrics": metrics,
        "facts": facts,
    }


def main(path: str) -> None:
    pages = Path(path).read_text(encoding="utf-8").split("\f")
    table14, fig57 = parse_table_14(pages[22]), parse_figure_57(pages[108])
    oecd14, oecd57 = table14.pop("OECD"), fig57.pop("OECD")
    OUT.mkdir(parents=True, exist_ok=True)
    for country in sorted(table14):
        data = build(country, table14[country], fig57.get(country, {}), oecd14, oecd57,
                     country_sentences(pages, country))
        (OUT / f"{slug(country)}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{country:16} {len(data['facts']):3} facts")


if __name__ == "__main__":
    main(sys.argv[1])
