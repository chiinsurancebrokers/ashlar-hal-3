"""Ashlar client-facing PDF report generator using ReportLab."""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from .client_analysis import plan_display_name, premium_display, client_facing_deductible, find_plan_narrative

NAVY = colors.HexColor("#0C1A2A")
INK = colors.HexColor("#1C2537")
MUTED = colors.HexColor("#6C768A")
PURPLE = colors.HexColor("#6C4CF5")
GOLD = colors.HexColor("#E7AD43")
GREEN = colors.HexColor("#15966A")
BORDER = colors.HexColor("#E1E7EF")
LIGHT = colors.HexColor("#F6F8FB")
WHITE = colors.white


def _labels(language: str) -> dict:
    greek = str(language).lower().startswith(("gr", "el")) or "greek" in str(language).lower()
    if greek:
        return {
            "subtitle": "Ανεξάρτητη συγκριτική ανάλυση και αιτιολογημένη συμβουλευτική άποψη",
            "footer": "Ανεξάρτητη συγκριτική ανάλυση",
            "context": "Πλαίσιο πελάτη",
            "profile": "Προφίλ / πλαίσιο",
            "exec": "Συνοπτική εικόνα",
            "strengths": "Πλεονεκτήματα",
            "consider": "Σημεία προσοχής",
            "compare": "Συγκριτικός πίνακας",
            "compare_note": "Ο πίνακας παρουσιάζει συνοπτικά τους όρους που εξήχθησαν από τα διαθέσιμα έγγραφα. Τα συμβατικά έγγραφα παραμένουν δεσμευτικά.",
            "benefit": "Κάλυψη / όρος",
            "diff": "Κύριες διαφορές",
            "assessment": "Πρόταση Ashlar",
            "our_view": "Η πρότασή μας",
            "preferred": "Προτεινόμενη επιλογή",
            "alternative": "Ισχυρή εναλλακτική",
            "extras": "Επιλογή με ευρύτερα πρόσθετα",
            "budget": "Οικονομικότερη επιλογή",
            "important_next": "Σημαντικές επισημάνσεις & επόμενα βήματα",
            "important": "Σημαντικές επισημάνσεις",
            "next": "Επόμενα βήματα",
            "notice": "Σημαντική σημείωση",
            "sources": "Επίσημα έγγραφα ασφαλιστικών εταιρειών",
            "sources_note": "Τα παρακάτω brochures / Tables of Benefits είναι τα έγγραφα των ασφαλιστικών εταιρειών που συνοδεύουν την ανάλυση. Οι προσωρινοί σύνδεσμοι ενδέχεται να λήξουν.",
            "open_doc": "Άνοιγμα εγγράφου",
        }
    return {
        "subtitle": "Independent plan comparison and reasoned advisory view",
        "footer": "Independent comparative analysis",
        "context": "Client context",
        "profile": "Profile / context",
        "exec": "Executive summary",
        "strengths": "Strengths",
        "consider": "Points to consider",
        "compare": "Side-by-side comparison",
        "compare_note": "The table below presents the extracted plan terms side by side. Long policy clauses are intentionally condensed for readability; governing documents remain controlling.",
        "benefit": "Benefit / term",
        "diff": "Key differences",
        "assessment": "Ashlar Recommendation",
        "our_view": "Our recommendation",
        "preferred": "Recommended option",
        "alternative": "Strong alternative",
        "extras": "Broader extras option",
        "budget": "Budget option",
        "important_next": "Important considerations & next steps",
        "important": "Important considerations",
        "next": "Next steps",
        "notice": "Important notice",
        "sources": "Official provider documents",
        "sources_note": "The brochures / Tables of Benefits below are the insurer documents supplied with this analysis. Temporary web links may expire.",
        "open_doc": "Open document",
    }


def _register_fonts():
    regular_candidates = [
        "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    reg = next((p for p in regular_candidates if Path(p).exists()), None)
    bold = next((p for p in bold_candidates if Path(p).exists()), None)
    if reg and bold:
        pdfmetrics.registerFont(TTFont("AshlarSans", reg))
        pdfmetrics.registerFont(TTFont("AshlarSansBold", bold))
        return "AshlarSans", "AshlarSansBold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = _register_fonts()


def _p(text, style):
    return Paragraph(str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def build_pdf_bytes(*, client_analysis: dict, results: list[dict], language: str = "English", source_documents: list[dict] | None = None) -> bytes:
    lab = _labels(language)
    buf = io.BytesIO()
    page = landscape(A4)
    doc = BaseDocTemplate(
        buf,
        pagesize=page,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=17 * mm,
        bottomMargin=14 * mm,
        title=client_analysis.get("report_title") or "Ashlar Insurance Comparative Analysis",
        author="Ashlar Assurance",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")

    def on_page(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, page[1] - 8 * mm, page[0], 8 * mm, stroke=0, fill=1)
        canvas.setFillColor(GOLD)
        canvas.rect(0, page[1] - 8 * mm, 4 * mm, 8 * mm, stroke=0, fill=1)
        canvas.setFont(FONT_BOLD, 8)
        canvas.setFillColor(WHITE)
        canvas.drawString(15 * mm, page[1] - 5.3 * mm, "ASHLAR ASSURANCE")
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 6 * mm, lab["footer"])
        canvas.drawRightString(page[0] - 15 * mm, 6 * mm, f"{date.today().strftime('%d %b %Y')}  |  {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=on_page))
    styles = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName=FONT_BOLD, fontSize=22, leading=27, textColor=INK, spaceAfter=8)
    H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName=FONT_BOLD, fontSize=14, leading=18, textColor=INK, spaceBefore=5, spaceAfter=6)
    Body = ParagraphStyle("Body", parent=styles["BodyText"], fontName=FONT, fontSize=9.2, leading=13.2, textColor=INK, spaceAfter=5)
    Small = ParagraphStyle("Small", parent=Body, fontSize=7.3, leading=9.6, textColor=MUTED)
    WhiteH = ParagraphStyle("WhiteH", parent=H1, textColor=WHITE, fontSize=25, leading=29)
    WhiteBody = ParagraphStyle("WhiteBody", parent=Body, textColor=colors.HexColor("#D4DFEA"), fontSize=10.5, leading=14.5)
    Bullet = ParagraphStyle("Bullet", parent=Body, leftIndent=10, firstLineIndent=-7, bulletIndent=0)

    story = []
    cover = Table(
        [
            [_p("ASHLAR ASSURANCE", ParagraphStyle("Eyebrow", parent=Body, fontName=FONT_BOLD, fontSize=8.5, textColor=GOLD))],
            [_p(client_analysis.get("report_title") or "Insurance Comparative Analysis", WhiteH)],
            [_p(client_analysis.get("client_name") or "Client", ParagraphStyle("Client", parent=WhiteH, fontSize=16.5, leading=20))],
            [_p(lab["subtitle"], WhiteBody)],
        ],
        colWidths=[doc.width],
        rowHeights=[10 * mm, 42 * mm, 12 * mm, 17 * mm],
    )
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("BOX", (0, 0), (-1, -1), 0, NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 10 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story += [Spacer(1, 10 * mm), cover, PageBreak()]

    story += [
        _p(lab["context"], H1),
        _p(client_analysis.get("client_needs_summary") or client_analysis.get("client_priorities") or "No specific priorities supplied.", Body),
        Spacer(1, 3 * mm),
    ]
    profile = client_analysis.get("client_profile")
    if profile and profile != "Not supplied":
        story += [_p(lab["profile"], H2), _p(profile, Body)]
    story += [_p(lab["exec"], H2), _p(client_analysis.get("executive_summary") or "", Body), PageBreak()]

    narrative_plans = client_analysis.get("plans", [])
    for result in results:
        a = result.get("analysis") or {}
        key = (a.get("provider") or result.get("provider"), a.get("plan_name") or result.get("target_plan"))
        n = find_plan_narrative(narrative_plans, result)
        story += [_p(f"{key[0]} - {key[1]}", H1)]
        facts = [
            ["Premium", premium_display(a), "Annual limit", a.get("annual_limit") or "Not specified"],
            ["Deductible / excess", client_facing_deductible(a.get("deductible_or_excess") or "Not specified"), "Area", a.get("area_of_cover") or "Not specified"],
        ]
        fact_tbl = Table(
            [[_p(c, Small if i % 2 == 0 else Body) for i, c in enumerate(row)] for row in facts],
            colWidths=[30 * mm, 85 * mm, 30 * mm, 105 * mm],
        )
        fact_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                    ("GRID", (0, 0), (-1, -1), .35, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story += [fact_tbl, Spacer(1, 4 * mm), _p(n.get("summary") or "", Body)]
        cols = []
        for title, items, accent in [
            (lab["strengths"], n.get("strengths") or [], GREEN),
            (lab["consider"], n.get("considerations") or [], GOLD),
        ]:
            parts = [_p(title, ParagraphStyle(title, parent=H2, textColor=accent))]
            parts += [_p("• " + str(x), Bullet) for x in items[:5]]
            cols.append(parts)
        two = Table([cols], colWidths=[125 * mm, 125 * mm])
        two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm)]))
        story += [two, PageBreak()]

    story += [_p(lab["compare"], H1), _p(lab["compare_note"], Small)]
    matrix = client_analysis.get("comparison_matrix") or []
    names = [plan_display_name(r) for r in results]
    header = [_p(lab["benefit"], ParagraphStyle("TH", parent=Small, fontName=FONT_BOLD, textColor=WHITE))] + [
        _p(n, ParagraphStyle("TH2", parent=Small, fontName=FONT_BOLD, textColor=WHITE, alignment=TA_CENTER))
        for n in names
    ]
    data = [header]
    for row in matrix:
        data.append(
            [_p(row.get("topic"), ParagraphStyle("Topic", parent=Small, fontName=FONT_BOLD, textColor=INK))]
            + [_p((row.get("values") or {}).get(n) or "Not specified", Small) for n in names]
        )
    first = 38 * mm
    other = (doc.width - first) / max(len(names), 1)
    comp = Table(data, colWidths=[first] + [other] * len(names), repeatRows=1)
    comp.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("GRID", (0, 0), (-1, -1), .3, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    for i in range(1, len(data)):
        if i % 2 == 0:
            comp.setStyle(TableStyle([("BACKGROUND", (0, i), (-1, i), LIGHT)]))
    story += [comp, PageBreak()]

    story += [_p(lab["diff"], H1)]
    for d in (client_analysis.get("key_differences") or [])[:6]:
        card = Table(
            [[
                _p(d.get("title") or "Difference", ParagraphStyle("DT", parent=H2, textColor=PURPLE)),
                _p(d.get("analysis") or "", Body),
                _p(d.get("client_impact") or "", Small),
            ]],
            colWidths=[55 * mm, 125 * mm, 70 * mm],
        )
        card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                    ("BOX", (0, 0), (-1, -1), .4, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story += [card, Spacer(1, 2.5 * mm)]

    story += [PageBreak(), _p(lab["assessment"], H1)]
    ass = client_analysis.get("ashlar_assessment") or {}
    story += [_p(ass.get("headline") or lab["our_view"], ParagraphStyle("AHead", parent=H2, fontSize=16.5, leading=21, textColor=PURPLE))]
    if ass.get("recommended_provider") or ass.get("recommended_plan"):
        story += [
            _p(
                f"{lab['preferred']}: {ass.get('recommended_provider', '')} {ass.get('recommended_plan', '')}",
                ParagraphStyle("Rec", parent=H2, textColor=GREEN),
            )
        ]
    for reason in ass.get("reasoning") or []:
        story += [_p("• " + str(reason), Bullet)]
    if ass.get("alternative_provider") or ass.get("alternative_plan"):
        story += [
            Spacer(1, 3 * mm),
            _p(lab["alternative"], H2),
            _p(f"{ass.get('alternative_provider', '')} {ass.get('alternative_plan', '')}", Body),
            _p(ass.get("alternative_reason") or "", Body),
            _p(ass.get("when_the_alternative_may_be_better") or "", Small),
        ]
    if ass.get("extras_provider") or ass.get("extras_plan"):
        story += [
            Spacer(1, 2 * mm),
            _p(lab["extras"], H2),
            _p(f"{ass.get('extras_provider', '')} {ass.get('extras_plan', '')}", Body),
            _p(ass.get("extras_reason") or "", Small),
        ]
    if ass.get("budget_provider") or ass.get("budget_plan"):
        story += [
            Spacer(1, 2 * mm),
            _p(lab["budget"], H2),
            _p(f"{ass.get('budget_provider', '')} {ass.get('budget_plan', '')}", Body),
            _p(ass.get("budget_reason") or "", Small),
        ]

    story += [PageBreak(), _p(lab["important_next"], H1), _p(lab["important"], H2)]
    for item in client_analysis.get("important_considerations") or []:
        story += [_p("• " + str(item), Bullet)]
    story += [_p(lab["next"], H2)]
    for item in client_analysis.get("next_steps") or []:
        story += [_p("• " + str(item), Bullet)]
    story += [Spacer(1, 5 * mm), _p(lab["notice"], H2), _p(client_analysis.get("disclaimer") or "", Small)]

    source_documents = source_documents or []
    if source_documents:
        story += [PageBreak(), _p(lab["sources"], H1), _p(lab["sources_note"], Small), Spacer(1, 3 * mm)]
        grouped: dict[str, list[dict]] = {}
        for src in source_documents:
            provider = str(src.get("provider") or "Provider")
            grouped.setdefault(provider, []).append(src)
        for provider, docs_for_provider in grouped.items():
            story += [_p(provider, H2)]
            for src in docs_for_provider:
                filename = str(src.get("filename") or "Provider document")
                doc_type = str(src.get("doc_type") or "document").replace("_", " ").title()
                plan_name = str(src.get("plan_name") or "").strip()
                prefix = f"{doc_type} - {plan_name}" if plan_name else doc_type
                url = str(src.get("url") or "").strip()
                if url:
                    link_markup = (
                        f"<b>{xml_escape(prefix)}</b>: {xml_escape(filename)} "
                        f"- <link href={quoteattr(url)} color='#6C4CF5'>{xml_escape(lab['open_doc'])}</link>"
                    )
                    story += [Paragraph(link_markup, Body)]
                else:
                    story += [_p(f"{prefix}: {filename} (supplied separately in the client pack)", Body)]
            story += [Spacer(1, 2 * mm)]

    doc.build(story)
    return buf.getvalue()
