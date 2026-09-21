"""Deterministic target-plan isolation for multi-plan carrier brochures.

The document model must never see neighbouring plan columns as if they belonged
to the selected plan. This extractor uses PyMuPDF table geometry to isolate one
plan column before any LLM analysis. It supports normal table headers, plan
names inside an early table row, and continuation tables where the carrier does
not repeat plan headings on the following page/table.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

import fitz


_LABEL_HEADERS = {
    "benefit", "benefits", "plan details", "coverage", "cover", "service",
    "services", "feature", "features", "benefit / term", "benefit/term",
}
_CHECKMARKS = {"\uf0fc", "", "✓", "✔", "☑"}


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _key(value: str | None) -> str:
    return _norm(value).casefold()


def _cell_text(page: fitz.Page, cell) -> str:
    if not cell:
        return ""
    try:
        return _norm(page.get_text("text", clip=fitz.Rect(cell), sort=True))
    except Exception:
        return ""


def _normalise_value(value: str) -> tuple[str, str]:
    value = _norm(value)
    if not value:
        return "", "text"
    if value[0] in _CHECKMARKS:
        rest = _norm(value[1:])
        return (f"Covered (table checkmark); {rest}" if rest else "Covered (table checkmark)"), "embedded_checkmark"
    if value in _CHECKMARKS:
        return "Covered (table checkmark)", "embedded_checkmark"
    return value, "text"


@dataclass
class PlanTableRow:
    page: int
    table_index: int
    section: str
    benefit: str
    value: str
    target_plan: str
    evidence_type: str = "text"


@dataclass
class PlanTableExtraction:
    target_plan: str
    rows: list[PlanTableRow]
    pages_with_target_tables: list[int]
    available_plan_headers: list[str]

    def as_dict(self) -> dict:
        return {
            "target_plan": self.target_plan,
            "rows": [asdict(row) for row in self.rows],
            "pages_with_target_tables": self.pages_with_target_tables,
            "available_plan_headers": self.available_plan_headers,
        }

    def to_prompt_context(self, max_rows: int = 260) -> str:
        lines = [
            f"TARGET PLAN TABLE EVIDENCE — {self.target_plan}",
            "This evidence was isolated geometrically from the selected plan column.",
            "Treat 'Covered (table checkmark)' as a visual checkmark in that plan's cell.",
            "Do not use values from neighbouring plan columns.",
            "",
        ]
        current_section = None
        for row in self.rows[:max_rows]:
            if row.section and row.section != current_section:
                current_section = row.section
                lines.append(f"[Page {row.page}] SECTION: {current_section}")
            lines.append(f"[Page {row.page}] {row.benefit} => {row.value}")
        return "\n".join(lines)


def _target_header_index(headers: list[str], target_plan: str) -> int | None:
    target = _key(target_plan)
    for index, header in enumerate(headers):
        if _key(header) == target:
            return index
    return None


def _row_texts(page: fitz.Page, row) -> list[str]:
    return [_cell_text(page, cell) for cell in row.cells]


def _internal_plan_row(page: fitz.Page, table, target_plan: str) -> tuple[int, int] | None:
    target = _key(target_plan)
    for row_index, row in enumerate(table.rows[:6]):
        for column_index, text in enumerate(_row_texts(page, row)):
            if _key(text) == target:
                return row_index, column_index
    return None


def _infer_label_index(page: fitz.Page, table, target_idx: int, start_row: int = 0) -> int:
    if target_idx <= 0:
        return 0
    headers = [_norm(value) for value in table.header.names]
    for index in range(min(target_idx, len(headers)) - 1, -1, -1):
        if _key(headers[index]) in _LABEL_HEADERS:
            return index

    scores: list[tuple[int, int, int]] = []
    for index in range(target_idx):
        nonempty = chars = 0
        for row in table.rows[start_row:min(len(table.rows), start_row + 14)]:
            if index >= len(row.cells):
                continue
            text = _cell_text(page, row.cells[index])
            if text:
                nonempty += 1
                chars += len(text)
        scores.append((nonempty, chars, index))
    return max(scores)[2] if scores else max(0, target_idx - 1)


def _compatible_continuation(table, geometry: dict, page_number: int) -> bool:
    if not geometry or page_number - geometry.get("page", page_number) > 1:
        return False
    prior = geometry.get("table_bbox")
    bbox = table.bbox
    if prior and (abs(bbox[0] - prior[0]) > 14 or abs(bbox[2] - prior[2]) > 14):
        return False
    tx0, tx1 = geometry["target_x"]
    lx0, lx1 = geometry["label_x"]
    return bbox[0] - 2 <= lx0 < lx1 <= bbox[2] + 2 and bbox[0] - 2 <= tx0 < tx1 <= bbox[2] + 2


def _small_vector_icons(page: fitz.Page, rect: fitz.Rect) -> list[fitz.Rect]:
    icons: list[fitz.Rect] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return icons
    for drawing in drawings:
        candidate = fitz.Rect(drawing.get("rect", (0, 0, 0, 0)))
        if candidate.is_empty or not candidate.intersects(rect):
            continue
        if not (1 < candidate.width <= 20 and 1 < candidate.height <= 20):
            continue
        intersection = candidate & rect
        if candidate.get_area() and intersection.get_area() >= 0.60 * candidate.get_area():
            icons.append(candidate)
    return icons


def extract_target_plan_from_pdf(
    pdf_path: str | Path,
    target_plan: str,
    *,
    max_rows: int = 300,
) -> PlanTableExtraction:
    """Return only the selected plan's benefit/value cells from a brochure PDF."""
    rows: list[PlanTableRow] = []
    pages: list[int] = []
    headers_seen: list[str] = []
    current_section = ""
    last_geometry: dict | None = None

    doc = fitz.open(str(Path(pdf_path)))
    try:
        for page_number, page in enumerate(doc, start=1):
            try:
                tables = page.find_tables().tables
            except Exception:
                tables = []

            for table_index, table in enumerate(tables):
                headers = [_norm(value) for value in table.header.names]
                target_idx = _target_header_index(headers, target_plan)
                label_idx: int | None = None
                target_x = label_x = None
                start_row = 1
                source = "table_header"

                if target_idx is not None and target_idx < len(table.header.cells) and table.header.cells[target_idx]:
                    target_cell = table.header.cells[target_idx]
                    target_x = (target_cell[0], target_cell[2])
                    label_idx = _infer_label_index(page, table, target_idx, 1)
                    if label_idx < len(table.header.cells) and table.header.cells[label_idx]:
                        label_cell = table.header.cells[label_idx]
                        label_x = (label_cell[0], label_cell[2])
                    section = headers[label_idx] if label_idx is not None and label_idx < len(headers) else ""
                    if section and _key(section) not in _LABEL_HEADERS:
                        current_section = section
                else:
                    internal = _internal_plan_row(page, table, target_plan)
                    if internal:
                        plan_row_idx, target_idx = internal
                        plan_row = table.rows[plan_row_idx]
                        if target_idx < len(plan_row.cells) and plan_row.cells[target_idx]:
                            target_cell = plan_row.cells[target_idx]
                            target_x = (target_cell[0], target_cell[2])
                            label_idx = _infer_label_index(page, table, target_idx, plan_row_idx + 1)
                            label_cell = plan_row.cells[label_idx] if label_idx < len(plan_row.cells) else None
                            if not label_cell:
                                for probe in table.rows[plan_row_idx + 1:]:
                                    if label_idx < len(probe.cells) and probe.cells[label_idx]:
                                        label_cell = probe.cells[label_idx]
                                        break
                            if label_cell:
                                label_x = (label_cell[0], label_cell[2])
                            start_row = plan_row_idx + 1
                            source = "internal_plan_row"
                            for text in _row_texts(page, plan_row):
                                if text and text not in headers_seen:
                                    headers_seen.append(text)
                    elif _compatible_continuation(table, last_geometry or {}, page_number):
                        target_x = last_geometry["target_x"]
                        label_x = last_geometry["label_x"]
                        target_idx = last_geometry.get("target_idx")
                        label_idx = last_geometry.get("label_idx")
                        start_row = 0
                        source = "continuation_geometry"
                        first = _row_texts(page, table.rows[0]) if table.rows else []
                        nonempty = [text for text in first if text]
                        if len(nonempty) == 1 and len(nonempty[0]) <= 180:
                            current_section = nonempty[0]
                            start_row = 1

                if not target_x or not label_x:
                    continue
                if page_number not in pages:
                    pages.append(page_number)
                for header in headers:
                    if header and header not in headers_seen:
                        headers_seen.append(header)

                last_geometry = {
                    "page": page_number,
                    "target_x": target_x,
                    "label_x": label_x,
                    "target_idx": target_idx,
                    "label_idx": label_idx,
                    "table_bbox": table.bbox,
                    "source": source,
                }
                tx0, tx1 = target_x
                lx0, lx1 = label_x

                for table_row in table.rows[start_row:]:
                    first_cell = next((cell for cell in table_row.cells if cell), None)
                    if first_cell is None:
                        continue
                    y0, y1 = first_cell[1], first_cell[3]
                    label_rect = fitz.Rect(lx0, y0, lx1, y1)
                    target_rect = fitz.Rect(tx0, y0, tx1, y1)
                    label = _norm(page.get_text("text", clip=label_rect, sort=True))
                    raw_value = _norm(page.get_text("text", clip=target_rect, sort=True))
                    value, evidence_type = _normalise_value(raw_value)

                    if not label:
                        full_row = _norm(page.get_text("text", clip=fitz.Rect(table.bbox[0], y0, table.bbox[2], y1), sort=True))
                        if full_row and len(full_row) <= 180:
                            current_section = full_row
                        continue
                    if not value:
                        if _small_vector_icons(page, target_rect):
                            value, evidence_type = "Covered (table checkmark)", "vector_checkmark"
                        else:
                            value, evidence_type = "Not stated / blank cell", "blank"

                    rows.append(PlanTableRow(
                        page=page_number,
                        table_index=table_index,
                        section=current_section,
                        benefit=label,
                        value=value,
                        target_plan=target_plan,
                        evidence_type=evidence_type,
                    ))
                    if len(rows) >= max_rows:
                        return PlanTableExtraction(target_plan, rows, pages, headers_seen)
    finally:
        doc.close()

    return PlanTableExtraction(target_plan, rows, pages, headers_seen)
