from pathlib import Path

import fitz

from backend.app.documents.brochure_tables import extract_target_plan_from_pdf


def _make_comparison_pdf(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=600, height=500)
    xs = [50, 300, 400, 500, 550]
    ys = [60, 100, 145, 190, 235]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.8)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)

    headers = ["Benefit", "Bronze", "Silver", "Gold"]
    for index, text in enumerate(headers):
        page.insert_text((xs[index] + 5, 85), text, fontsize=10)

    rows = [
        ("Annual overall benefit maximum", "EUR 500,000", "EUR 800,000", "EUR 2,000,000"),
        ("Outpatient annual maximum", "EUR 5,000", "EUR 12,000", "EUR 25,000"),
        ("Mental health", "EUR 1,000", "EUR 3,700", "EUR 7,500"),
    ]
    for row_index, values in enumerate(rows, start=1):
        for column_index, text in enumerate(values):
            page.insert_textbox(
                fitz.Rect(xs[column_index] + 4, ys[row_index] + 3, xs[column_index + 1] - 4, ys[row_index + 1] - 3),
                text,
                fontsize=8,
            )
    doc.save(path)
    doc.close()


def test_geometric_target_plan_isolation_does_not_leak_gold(tmp_path):
    pdf = tmp_path / "multi_plan.pdf"
    _make_comparison_pdf(pdf)
    result = extract_target_plan_from_pdf(pdf, "Silver")
    values = "\n".join(row.value for row in result.rows)

    assert "EUR 800,000" in values
    assert "EUR 12,000" in values
    assert "EUR 2,000,000" not in values
    assert "EUR 25,000" not in values
    assert all(row.target_plan == "Silver" for row in result.rows)
