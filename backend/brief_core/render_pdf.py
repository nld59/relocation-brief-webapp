from __future__ import annotations

"""PDF renderer (premium, multi-page).

This replaces the previous canvas-based one-page renderer.
We use ReportLab Platypus so content can naturally flow across pages.

The public entrypoint is `render_minimal_premium_pdf(...)` because the
rest of the app imports that name.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    ListFlowable,
    ListItem,
    KeepTogether,
)


ACCENT = colors.HexColor("#2F66FF")
BG_SOFT = colors.HexColor("#F7F9FF")
BG_CARD = colors.HexColor("#FFFFFF")
STROKE = colors.HexColor("#E5E7EB")
TEXT_MUTED = colors.HexColor("#6B7280")


def _clean_text(s: Any) -> str:
    if s is None:
        return ""
    s = str(s)
    # Keep the PDF stable (avoid curly quotes / NBSP)
    return (
        s.replace("\u00A0", " ")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
    ).strip()


def _rating_bar(value: Any) -> str:
    """Render a compact 1–5 rating.

    Important: avoid unicode block characters here.
    Some PDF viewers/fonts render them as empty squares, which looks broken.
    """
    try:
        v = int(value)
    except Exception:
        v = 3
    v = max(1, min(5, v))
    return f"{v}/5"


def _bullets(items: List[str], style: ParagraphStyle) -> ListFlowable:
    items = [i for i in (items or []) if _clean_text(i)]
    if not items:
        items = ["—"]
    li = [ListItem(Paragraph(_clean_text(t), style), leftIndent=10) for t in items]
    return ListFlowable(li, bulletType="bullet", start="•", leftIndent=14)


def _numbered(items: List[str], style: ParagraphStyle) -> ListFlowable:
    items = [i for i in (items or []) if _clean_text(i)]
    if not items:
        items = ["—"]
    li = [ListItem(Paragraph(_clean_text(t), style), leftIndent=10) for t in items]
    return ListFlowable(li, bulletType="1", leftIndent=16)


def _section_title(text: str, styles) -> Paragraph:
    return Paragraph(_clean_text(text), styles["H2"])


def _card(elements: List[Any], padding: float = 10, *, width: Optional[float] = None) -> Table:
    """Wrap a list of flowables in a rounded-ish card.

    IMPORTANT: the card width must match the container.
    If we always use full-page width and then place cards into a 2-column table,
    ReportLab will let the inner table overflow and visually overlap.
    """
    card_w = float(width) if width else (A4[0] - 4 * cm)
    tbl = Table([[elements]], colWidths=[card_w])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BG_CARD),
                ("BOX", (0, 0), (-1, -1), 0.8, STROKE),
                ("LEFTPADDING", (0, 0), (-1, -1), padding),
                ("RIGHTPADDING", (0, 0), (-1, -1), padding),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
            ]
        )
    )
    return tbl


def _two_col_grid(left: List[Any], right: List[Any], gap: float = 10) -> Table:
    w_total = A4[0] - 4 * cm
    w = (w_total - gap) / 2.0
    tbl = Table([[left, right]], colWidths=[w, w], hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return tbl


def _header_footer(canvas, doc, title: str):
    canvas.saveState()
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(2 * cm, A4[1] - 1.2 * cm, _clean_text(title))
    canvas.drawRightString(A4[0] - 2 * cm, A4[1] - 1.2 * cm, date.today().isoformat())
    canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def render_minimal_premium_pdf(
    out_path: str,
    city: str,
    brief: Dict[str, Any],
    answers: Optional[Dict[str, str]] = None,
) -> None:
    """Render a premium, multi-page PDF relocation brief."""

    answers = answers or {}

    styles_src = getSampleStyleSheet()
    styles: Dict[str, ParagraphStyle] = {
        "Title": ParagraphStyle(
            "Title",
            parent=styles_src["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.black,
            spaceAfter=10,
        ),
        "H2": ParagraphStyle(
            "H2",
            parent=styles_src["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=15,
            textColor=ACCENT,
            spaceBefore=6,
            spaceAfter=6,
        ),
        "H3": ParagraphStyle(
            "H3",
            parent=styles_src["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            textColor=colors.black,
            spaceBefore=6,
            spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=10.2,
            leading=13,
            spaceAfter=6,
        ),
        "Small": ParagraphStyle(
            "Small",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12,
            textColor=TEXT_MUTED,
        ),
        "Bullet": ParagraphStyle(
            "Bullet",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=10.0,
            leading=13,
        ),
        "Link": ParagraphStyle(
            "Link",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=10.0,
            leading=13,
            textColor=ACCENT,
        ),
    }

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.6 * cm,
        title=f"Relocation Brief — {city}",
        author="Relocation Brief",
    )

    story: List[Any] = []

    # For any 2-column layouts we must size cards to the column width,
    # otherwise inner tables overflow and overlap visually.
    page_w = A4[0] - 4 * cm
    col_gap = 12
    col_w = (page_w - col_gap) / 2.0

    # Cover title
    story.append(Paragraph(f"Relocation Brief — {_clean_text(city)}", styles["Title"]))
    story.append(Paragraph("A practical shortlist and action plan for the next 1–2 weeks.", styles["Small"]))
    story.append(Spacer(1, 10))

    # Executive summary (60-second scan)
    exec_rows = []
    for row in (brief.get("executive_summary") or [])[:3]:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name", "—"))
        best_for = "; ".join([_clean_text(x) for x in (row.get("best_for") or []) if _clean_text(x)])
        watch = "; ".join([_clean_text(x) for x in (row.get("watch") or []) if _clean_text(x)])
        microhoods = ", ".join([_clean_text(x) for x in (row.get("microhoods") or []) if _clean_text(x)])
        exec_rows.append([
            Paragraph(f"<b>{name}</b>", styles["Body"]),
            Paragraph(best_for or "—", styles["Body"]),
            Paragraph(watch or "—", styles["Body"]),
            Paragraph(microhoods or "—", styles["Body"]),
        ])

    if exec_rows:
        story.append(_section_title("Executive summary (quick scan)", styles))
        tbl = Table(
            [[
                Paragraph("<b>Commune</b>", styles["Small"]),
                Paragraph("<b>Best for</b>", styles["Small"]),
                Paragraph("<b>Watch-outs</b>", styles["Small"]),
                Paragraph("<b>Microhoods</b>", styles["Small"]),
            ]] + exec_rows,
            colWidths=[3.2 * cm, 5.6 * cm, 5.2 * cm, 4.5 * cm],
            hAlign="LEFT",
        )
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BG_SOFT),
                    ("BOX", (0, 0), (-1, -1), 0.8, STROKE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, STROKE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(_card([tbl], padding=8))
        story.append(Spacer(1, 14))

    # 1) Client profile
    cp = _clean_text(brief.get("client_profile", ""))

    # A small factual snapshot from answers (keeps the report grounded even if LLM is vague)
    snapshot_lines: List[str] = []
    for key, label in [
        ("family", "Household"),
        ("housing_type", "Housing"),
        ("budget_rent", "Budget (rent)"),
        ("budget_buy", "Budget (buy)"),
        ("priorities", "Priorities"),
        ("office_commute", "Work commute"),
        ("school_commute", "School commute"),
    ]:
        v = _clean_text((answers or {}).get(key, ""))
        if v:
            snapshot_lines.append(f"<b>{label}:</b> {v}")

    left = [
        _section_title("Client profile", styles),
        Paragraph(cp or "—", styles["Body"]),
    ]
    if snapshot_lines:
        left.append(Spacer(1, 2))
        left.append(Paragraph("<b>Snapshot</b>", styles["Body"]))
        left.append(_bullets(snapshot_lines, styles["Bullet"]))

    story.append(_card(left))
    story.append(Spacer(1, 12))

    # Methodology (trust)
    meth = brief.get("methodology") or {}
    if isinstance(meth, dict):
        inputs = meth.get("inputs") or []
        matching = meth.get("matching") or []
        if inputs or matching:
            blocks = [_section_title("How this shortlist was matched", styles)]
            if inputs:
                blocks.append(Paragraph("<b>Inputs used</b>", styles["Body"]))
                blocks.append(_bullets([_clean_text(x) for x in inputs], styles["Bullet"]))
            if matching:
                blocks.append(Paragraph("<b>Matching logic</b>", styles["Body"]))
                blocks.append(_bullets([_clean_text(x) for x in matching], styles["Bullet"]))
            story.append(_card(blocks, padding=12))
            story.append(Spacer(1, 14))

    # 2) Must-have / Nice-to-have / Red flags / Trade-offs
    def _pill_box(title: str, items: List[str]) -> List[Any]:
        return [
            Paragraph(_clean_text(title), styles["H3"]),
            _bullets([_clean_text(x) for x in (items or [])], styles["Bullet"]),
        ]

    grid = _two_col_grid(
        _card(_pill_box("Must-have", brief.get("must_have", [])), padding=10, width=col_w),
        _card(_pill_box("Nice-to-have", brief.get("nice_to_have", [])), padding=10, width=col_w),
        gap=col_gap,
    )
    story.append(grid)
    story.append(Spacer(1, 12))

    grid2 = _two_col_grid(
        _card(_pill_box("Red flags", brief.get("red_flags", [])), padding=10, width=col_w),
        _card(_pill_box("Trade-offs", brief.get("contradictions", [])), padding=10, width=col_w),
        gap=col_gap,
    )
    story.append(grid2)
    story.append(Spacer(1, 16))

    # 3) Top-3 communes (multi-page, no forced limit)
    story.append(_section_title("Top-3 communes shortlist", styles))
    story.append(Paragraph("Each option includes strengths, trade-offs, and 2–3 microhoods to start your search.", styles["Small"]))
    story.append(Spacer(1, 6))

    districts = brief.get("top_districts") or []
    for idx, d in enumerate(districts[:3], 1):
        name = _clean_text(d.get("name", "—"))
        scores = d.get("scores") or {}
        micro_anchors = d.get("micro_anchors") or []
        priority_snapshot = d.get("priority_snapshot") or {}

        why = d.get("why") or []
        watch_out = d.get("watch_out") or []
        strengths = d.get("strengths") or []
        tradeoffs = d.get("tradeoffs") or []

        # If enrichers didn't create strengths/tradeoffs, fallback
        if not strengths:
            strengths = why
        if not tradeoffs:
            tradeoffs = watch_out

        header = [
            Paragraph(f"{idx}. <b>{name}</b>", ParagraphStyle("AreaTitle", parent=styles["Body"], fontSize=13, leading=16)),
        ]
        if micro_anchors:
            anchors_txt = ", ".join([_clean_text(a) for a in micro_anchors[:3] if _clean_text(a)])
            if anchors_txt:
                header.append(Paragraph(f"<font color='{TEXT_MUTED.hexval()}'>Landmarks (anchors):</font> {anchors_txt}", styles["Small"]))

        # Score row
        score_parts = []
        for k in ["Safety", "Family", "Commute", "Lifestyle", "BudgetFit", "Overall"]:
            if k in scores:
                score_parts.append(f"<b>{k}:</b> {_rating_bar(scores.get(k))}")
        if score_parts:
            header.append(Paragraph(" · ".join(score_parts), styles["Small"]))

        blocks: List[Any] = []
        blocks.extend(header)
        blocks.append(Spacer(1, 6))

        # Strengths & trade-offs
        blocks.append(Paragraph("<b>Key strengths</b>", styles["Body"]))
        blocks.append(_bullets([_clean_text(x) for x in strengths], styles["Bullet"]))
        blocks.append(Spacer(1, 4))
        blocks.append(Paragraph("<b>Trade-offs to watch</b>", styles["Body"]))
        blocks.append(_bullets([_clean_text(x) for x in tradeoffs], styles["Bullet"]))

        # Priorities snapshot (explicitly answers manager's 3.2)
        if isinstance(priority_snapshot, dict) and priority_snapshot:
            snap_lines = []
            for k in ["housing_cost", "transit", "commute_access", "schools_family"]:
                v = _clean_text(priority_snapshot.get(k, ""))
                if v:
                    label = {
                        "housing_cost": "Typical housing cost",
                        "transit": "Public transport",
                        "commute_access": "Commute access",
                        "schools_family": "Schools & family",
                    }.get(k, k)
                    snap_lines.append(f"<b>{label}:</b> {v}")
            if snap_lines:
                blocks.append(Spacer(1, 6))
                blocks.append(Paragraph("<b>Priorities snapshot</b>", styles["Body"]))
                blocks.append(_bullets(snap_lines, styles["Bullet"]))

        # Microhoods
        microhoods = d.get("microhoods") or []
        if microhoods:
            blocks.append(Spacer(1, 6))
            blocks.append(Paragraph("<b>Microhoods to start with</b>", styles["Body"]))
            mh_items: List[Any] = []
            for mh in microhoods[:3]:
                if not isinstance(mh, dict):
                    continue
                mh_name = _clean_text(mh.get("name", "")) or "—"
                mh_why = _clean_text(mh.get("why", ""))
                mh_wo = _clean_text(mh.get("watch_out", ""))
                mh_items.append(Paragraph(f"<b>{mh_name}</b>", styles["Body"]))
                if mh_why:
                    mh_items.append(Paragraph(f"<font color='{TEXT_MUTED.hexval()}'>Why:</font> {mh_why}", styles["Body"]))
                if mh_wo:
                    mh_items.append(Paragraph(f"<font color='{TEXT_MUTED.hexval()}'>Watch-out:</font> {mh_wo}", styles["Body"]))
                mh_items.append(Spacer(1, 4))
            if mh_items:
                blocks.append(_card(mh_items, padding=10))

        story.append(_card(blocks, padding=12))
        story.append(Spacer(1, 12))

    # 4) Next steps (expanded)
    story.append(PageBreak())
    story.append(_section_title("Next steps (1–2 weeks)", styles))

    next_steps = [_clean_text(x) for x in (brief.get("next_steps") or []) if _clean_text(x)]
    if not next_steps:
        next_steps = [
            "Shortlist 8–12 listings across the 3 communes and set up viewings.",
            "For each listing, confirm total monthly cost and what utilities are included.",
            "Validate commute: do one test route at peak hours (metro/tram and by car).",
            "Ask about parking rules/permits and storage (cellar, bike room).",
            "Prepare a document pack (ID, proof of income, employer letter, bank statements).",
            "If buying: request EPC, urbanism/permit docs, and recent syndic/HOA minutes.",
        ]

    # Split into Week 1 / Week 2 for readability
    w1 = next_steps[:5]
    w2 = next_steps[5:10]
    if w1:
        story.append(Paragraph("<b>Week 1</b>", styles["Body"]))
        story.append(_numbered(w1, styles["Bullet"]))
        story.append(Spacer(1, 6))
    if w2:
        story.append(Paragraph("<b>Week 2</b>", styles["Body"]))
        story.append(_numbered(w2, styles["Bullet"]))
        story.append(Spacer(1, 10))

    # Practical checklists
    viewing = [_clean_text(x) for x in (brief.get("viewing_checklist") or []) if _clean_text(x)]
    if viewing:
        story.append(Paragraph("<b>Viewing checklist</b>", styles["Body"]))
        story.append(_bullets(viewing[:10], styles["Bullet"]))
        story.append(Spacer(1, 8))

    offer = [_clean_text(x) for x in (brief.get("offer_strategy") or []) if _clean_text(x)]
    if offer:
        story.append(Paragraph("<b>Offer / decision strategy</b>", styles["Body"]))
        story.append(_bullets(offer[:8], styles["Bullet"]))
        story.append(Spacer(1, 10))

    # Relocation essentials (beyond real estate)
    rel = brief.get("relocation_essentials") or {}
    if isinstance(rel, dict) and any(rel.get(k) for k in ["first_72h", "first_2_weeks", "first_2_months"]):
        story.append(_section_title("Relocation essentials", styles))
        story.append(Paragraph("Operational steps to avoid surprises once you arrive.", styles["Small"]))
        story.append(Spacer(1, 6))

        def _phase(title: str, key: str) -> List[Any]:
            items = [_clean_text(x) for x in (rel.get(key) or []) if _clean_text(x)]
            if not items:
                return []
            return [Paragraph(f"<b>{title}</b>", styles["Body"]), _bullets(items, styles["Bullet"])]

        left = _phase("First 72 hours", "first_72h") + _phase("First 2 weeks", "first_2_weeks")
        right = _phase("First 2 months", "first_2_months")
        if left or right:
            story.append(_two_col_grid(_card(left, padding=10, width=col_w), _card(right, padding=10, width=col_w), gap=col_gap))
            story.append(Spacer(1, 12))

    # Questions for agent/landlord
    q = [_clean_text(x) for x in (brief.get("questions_for_agent_landlord") or []) if _clean_text(x)]
    if q:
        story.append(Paragraph("<b>Questions to ask (agent / landlord)</b>", styles["Body"]))
        story.append(_bullets(q, styles["Bullet"]))
        story.append(Spacer(1, 10))

    # 5) Agencies & resources (fixed from city pack)
    story.append(_section_title("Agencies and resources", styles))
    story.append(Paragraph("Curated starting points for Belgium/Brussels.", styles["Small"]))
    story.append(Spacer(1, 6))

    def _link_line(item: Dict[str, Any]) -> str:
        name = _clean_text(item.get("name", "—"))
        url = _clean_text(item.get("url", ""))
        note = _clean_text(item.get("note", ""))
        if url:
            base = f"<link href='{url}' color='{ACCENT.hexval()}'>{name}</link>"
        else:
            base = name
        if note:
            return f"{base} <font color='{TEXT_MUTED.hexval()}'>— {note}</font>"
        return base

    agencies = brief.get("agencies") or []
    websites = brief.get("real_estate_sites") or []

    left_block: List[Any] = [Paragraph("<b>Agencies</b>", styles["Body"])]
    left_block.append(_numbered([_link_line(x) for x in agencies[:5] if isinstance(x, dict)], styles["Bullet"]))

    right_block: List[Any] = [Paragraph("<b>Websites</b>", styles["Body"])]
    right_block.append(_numbered([_link_line(x) for x in websites[:3] if isinstance(x, dict)], styles["Bullet"]))

    story.append(_two_col_grid(_card(left_block, padding=10, width=col_w), _card(right_block, padding=10, width=col_w), gap=col_gap))

    # Clarifying questions (should normally be empty by the time user downloads)
    clar = [_clean_text(x) for x in (brief.get("clarifying_questions") or []) if _clean_text(x)]
    if clar:
        story.append(Spacer(1, 14))
        story.append(_section_title("Open questions (to finalize the search)", styles))
        story.append(_bullets(clar, styles["Bullet"]))

    doc.build(
        story,
        onFirstPage=lambda c, d: _header_footer(c, d, f"Relocation Brief — {city}"),
        onLaterPages=lambda c, d: _header_footer(c, d, f"Relocation Brief — {city}"),
    )
