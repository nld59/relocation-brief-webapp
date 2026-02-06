from __future__ import annotations

"""PDF renderer (premium, multi-page).

This replaces the previous canvas-based one-page renderer.
We use ReportLab Platypus so content can naturally flow across pages.

The public entrypoint is `render_minimal_premium_pdf(...)` because the
rest of the app imports that name.
"""

from dataclasses import dataclass
from datetime import date
import re
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
    CondPageBreak,
)


ACCENT = colors.HexColor("#2F66FF")
BG_SOFT = colors.HexColor("#F7F9FF")
BG_CARD = colors.HexColor("#FFFFFF")
STROKE = colors.HexColor("#E5E7EB")
TEXT_MUTED = colors.HexColor("#6B7280")

# Displayed in footer for easier iteration and client support.
REPORT_VERSION = "v11.0"


def _truncate(text: Any, max_chars: int) -> str:
    """Hard truncate to keep summary tables scannable in auto-generated PDFs."""
    t = _clean_text(text)
    if len(t) <= max_chars:
        return t
    # Avoid breaking words too aggressively.
    cut = t[: max_chars - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


def _clean_text(s: Any) -> str:
    if s is None:
        return ""
    s = str(s)
    # Keep the PDF stable (avoid curly quotes / NBSP) and common punctuation artifacts.
    s = (
        s.replace("\u00A0", " ")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    # Remove odd ".;" / ";." artifacts which look unprofessional in tables.
    s = s.replace(".;", ".").replace(";.", ".").replace("..", ".")
    # Fix common LLM copy artifacts
    s = s.replace("What to check: Check:", "What to check:").replace("Check: Check:", "Check:")
    s = re.sub(r"\bRule of thumb:\s*Rule of thumb\b", "Rule of thumb", s)

    # Collapse excessive whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _format_link(item: Any) -> str:
    """Format an agency/website/link item as rich text.

    Accepts either a dict with {name, url, note} or a plain string.
    """
    if item is None:
        return "—"
    if isinstance(item, dict):
        name = _clean_text(item.get("name", "—"))
        url = _clean_text(item.get("url", ""))
        note = _clean_text(item.get("note", ""))
    else:
        name = _clean_text(item)
        url = ""
        note = ""

    if url:
        base = f"<link href='{url}' color='{ACCENT.hexval()}'>{name}</link>"
    else:
        base = name or "—"

    if note:
        return f"{base} <font color='{TEXT_MUTED.hexval()}'>— {note}</font>"
    return base


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
    items = [i for i in (items or []) if (t := _clean_text(i)) and t not in {'•', '-', '—'}]
    if not items:
        items = ["—"]
    li = [ListItem(Paragraph(_clean_text(t), style), leftIndent=10) for t in items]
    return ListFlowable(li, bulletType="bullet", start="•", leftIndent=14)


def _numbered(items: List[str], style: ParagraphStyle) -> ListFlowable:
    items = [i for i in (items or []) if (t := _clean_text(i)) and t not in {'•', '-', '—'}]
    if not items:
        items = ["—"]
    li = [ListItem(Paragraph(_clean_text(t), style), leftIndent=10) for t in items]
    return ListFlowable(li, bulletType="1", leftIndent=16)


def _numbered_table(items: List[str], styles: Dict[str, ParagraphStyle], *, width: Optional[float] = None) -> Table:
    """A cleaner numbered list than ListFlowable (numbers align like a proper report)."""
    clean = [_clean_text(i) for i in (items or []) if _clean_text(i)]
    if not clean:
        clean = ["—"]

    rows: List[List[Any]] = []
    for i, t in enumerate(clean, 1):
        rows.append(
            [
                Paragraph(f"<b>{i}</b>", styles["Small"]),
                Paragraph(t, styles["Body"]),
            ]
        )

    w_total = float(width) if width else (A4[0] - 4 * cm)
    tbl = Table(rows, colWidths=[0.55 * cm, w_total - 0.55 * cm - 2], hAlign="LEFT", splitByRow=1)
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return tbl


def _chips(scores: Dict[str, Any], styles: Dict[str, ParagraphStyle], keys: List[str]) -> Optional[Table]:
    """Small score chips for quick scanning (Family / Commute / Lifestyle + Overall)."""
    cells = []
    for k in keys:
        if k not in scores:
            continue
        cells.append(Paragraph(f"<b>{k}:</b> {_rating_bar(scores.get(k))}", styles["Small"]))
    if not cells:
        return None
    t = Table([cells], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BG_SOFT),
                ("BOX", (0, 0), (-1, -1), 0.6, STROKE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, STROKE),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return t


def _split_budget_reality(text: str) -> List[str]:
    """Split budget reality into 'Rule of thumb' and 'How to validate' when possible."""
    t = _clean_text(text)
    if not t:
        return []
    low = t.lower()
    # Try to split on validate/verify/check as a second bullet.
    for token in [" verify ", " validate ", " check ", " confirm ", " during viewings", " during viewing"]:
        idx = low.find(token)
        if idx > 40 and idx < len(t) - 25:
            left = t[:idx].rstrip(" ,.;:")
            right = t[idx:].lstrip()
            return [f"Rule of thumb: {left}", f"How to validate: {right}"]
    return [t]


def _section_title(text: str, styles) -> Paragraph:
    # A tiny underline gives a more "consulting report" feel without adding clutter.
    p = Paragraph(_clean_text(text), styles["H2"])
    w_total = A4[0] - 4 * cm
    t = Table([[p]], colWidths=[w_total], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 1.0, STROKE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def _kv_table(pairs: List[List[str]], styles: Dict[str, ParagraphStyle], *, col_widths: List[float]) -> Table:
    """Compact 2-col key/value table used for snapshots.

    Using tables (instead of bullet lists) improves scanability and removes
    "mystery empty bullets" that can appear with PDF text extraction.
    """
    rows = []
    for k, v in pairs:
        kk = _clean_text(k)
        vv = _clean_text(v)
        if not kk or not vv:
            continue
        rows.append([
            Paragraph(f"<b>{kk}</b>", styles["Small"]),
            Paragraph(vv, styles["Body"]),
        ])
    if not rows:
        rows = [[Paragraph("—", styles["Small"]), Paragraph("—", styles["Body"])]]

    tbl = Table(rows, colWidths=col_widths, hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return tbl


def _card(
    elements: List[Any],
    padding: float = 10,
    *,
    width: Optional[float] = None,
    repeat_first_row: bool = False,
) -> Table:
    """Wrap a list of flowables in a rounded-ish card.

    IMPORTANT:
    - The card width must match the container (especially in 2-column layouts).
    - Do NOT put a *list* of flowables into a single cell; split rows so Platypus can paginate.
    - If `repeat_first_row=True`, the first row (typically a header) will repeat when the
      card splits across pages — useful for long commune cards ("continued" UX).
    """
    card_w = float(width) if width else (A4[0] - 4 * cm)

    safe_elements = [e for e in (elements or []) if e is not None]
    if not safe_elements:
        safe_elements = [Paragraph("—", getSampleStyleSheet()["BodyText"])]

    data = [[e] for e in safe_elements]
    tbl = Table(
        data,
        colWidths=[card_w],
        splitByRow=1,
        repeatRows=1 if repeat_first_row else 0,
        hAlign="LEFT",
    )
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BG_CARD),
                                ("LEFTPADDING", (0, 0), (-1, -1), padding),
                ("RIGHTPADDING", (0, 0), (-1, -1), padding),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
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
    # Soft premium background
    canvas.saveState()
    canvas.setFillColor(BG_SOFT)
    canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)

    # Top accent line
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(2)
    canvas.line(0, A4[1] - 0.45 * cm, A4[0], A4[1] - 0.45 * cm)

    # Header / footer
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 8.2)
    canvas.drawString(2 * cm, A4[1] - 1.05 * cm, _clean_text(title))
    canvas.drawRightString(A4[0] - 2 * cm, A4[1] - 1.05 * cm, date.today().isoformat())
    # Footer: version + page
    canvas.drawString(2 * cm, 0.9 * cm, f"{REPORT_VERSION}")
    canvas.drawRightString(A4[0] - 2 * cm, 0.9 * cm, f"Page {doc.page}")
    canvas.restoreState()


def render_minimal_premium_pdf(
    out_path: str,
    city: str,
    brief: Dict[str, Any],
    answers: Optional[Dict[str, str]] = None,
) -> None:
    """Render a premium consulting-style relocation brief (10–12 pages).

    Design goals:
    - 60-second scanability (Action Plan + Executive Summary)
    - Trust (sources, scoring, assumptions)
    - Street-aware, actionable, and template-stable for auto-generated content
    """

    answers = answers or {}
    city_clean = _clean_text(city) or "—"

    styles_src = getSampleStyleSheet()
    # More compact typography vs v8 (designer feedback: -5–10% density).
    styles: Dict[str, ParagraphStyle] = {
        "Title": ParagraphStyle(
            "Title",
            parent=styles_src["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.black,
            spaceAfter=8,
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=10.0,
            leading=12.5,
            textColor=TEXT_MUTED,
            spaceAfter=10,
        ),
        "H2": ParagraphStyle(
            "H2",
            parent=styles_src["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.8,
            leading=12.8,
            textColor=ACCENT,
            spaceBefore=2,
            spaceAfter=3,
        ),
        "H3": ParagraphStyle(
            "H3",
            parent=styles_src["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=8.2,
            leading=10.2,
            textColor=colors.black,
            spaceBefore=3,
            spaceAfter=2,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.4,
            spaceAfter=2,
        ),
        "Small": ParagraphStyle(
            "Small",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=9.0,
            textColor=TEXT_MUTED,
            spaceAfter=1,
        ),
        "Bullet": ParagraphStyle(
            "Bullet",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.4,
        ),
        "Link": ParagraphStyle(
            "Link",
            parent=styles_src["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.4,
            textColor=ACCENT,
        ),
    }

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.25 * cm,
        bottomMargin=1.1 * cm,
        title=f"Relocation Brief — {city_clean}",
        author="Relocation Brief",
    )

    story: List[Any] = []
    page_w = A4[0] - 4 * cm
    col_gap = 10
    col_w = (page_w - col_gap) / 2.0

    # ----------------------------
    # Helper builders (stable, compact)
    # ----------------------------
    def _safe_list(xs: Any, *, max_n: int = 8) -> List[str]:
        out: List[str] = []
        for x in (xs or [])[: max_n]:
            t = _clean_text(x)
            if t:
                out.append(t)
        return out

    def _one_liner_from_commune(d: Dict[str, Any]) -> str:
        # Prefer explicit one_liner if present; else derive deterministically.
        s = _clean_text(d.get("one_liner", ""))
        if s:
            return _truncate(s, 110)
        # Derive from strengths/why without "generic" adjectives.
        cand = []
        for src in [d.get("strengths") or [], d.get("why") or []]:
            for it in src:
                t = _clean_text(it)
                if t and t.lower() not in {"family-friendly", "vibrant"}:
                    cand.append(t)
        if cand:
            return _truncate(cand[0], 110)
        return "Shortlist match based on your priorities and practical constraints."

    def _assumptions_block() -> List[Any]:
        pairs = []
        for k, label in [
            ("budget_buy", "Budget"),
            ("budget_rent", "Budget (rent)"),
            ("housing_type", "Target"),
            ("bedrooms", "Bedrooms"),
            ("family", "Household"),
            ("priorities", "Priorities"),
            ("has_car", "Car"),
        ]:
            v = _clean_text(answers.get(k, ""))
            if v:
                pairs.append([label, v])
        if not pairs:
            return [Paragraph("—", styles["Body"])]
        return [
            _kv_table(pairs, styles, col_widths=[3.0 * cm, page_w - 3.0 * cm - 16])
        ]

    def _sources_block() -> List[str]:
        # Keep it factual and stable; avoid claiming official stats unless wired.
        base = [
            "Immoweb / Zimmo / Immoscoop (listing supply & price checks)",
            "Google Maps (routes, street context), Street View (noise/arteries)",
            "STIB/MIVB network maps & schedules (public transport coverage)",
            "Commune / Brussels regional sites (parking permits, admin steps)",
        ]
        extra = _safe_list((brief.get("methodology") or {}).get("sources"), max_n=6)
        # Merge unique, preserve order
        out = []
        seen = set()
        for x in base + extra:
            key = x.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(x)
        return out[:8]

    def _portal_links() -> List[Dict[str, str]]:
        # Prefer brief-provided; otherwise stable Brussels defaults.
        sites = brief.get("real_estate_sites") or []
        if sites:
            return [x for x in sites if isinstance(x, dict)][:5]
        return [
            {"name": "Immoweb", "url": "https://www.immoweb.be", "note": "Largest Belgian property portal."},
            {"name": "Zimmo", "url": "https://www.zimmo.be", "note": "Popular portal; broad coverage."},
            {"name": "Immoscoop", "url": "https://www.immoscoop.be", "note": "Strong listings; many exclusives."},
            {"name": "Google Maps + Street View", "url": "https://maps.google.com", "note": "Save 12 candidates; check noise axes."},
            {"name": "STIB/MIVB Journey Planner", "url": "https://www.stib-mivb.be", "note": "Validate commute in peak hours."},
        ]



    def _pre_view_message_template() -> str:
        # Copy-paste friendly, BE context, not overly legal.
        return (
            "Hi, I'm interested in this property and would like to schedule a viewing. "
            "Before we confirm a time, could you please share/confirm the following:<br/>"
            "1) EPC rating + year of the last EPC<br/>"
            "2) Monthly charges (syndic/HOA) and what they include<br/>"
            "3) Reserve fund amount + planned works list (if apartment)<br/>"
            "4) Electrical compliance status (inspection report)<br/>"
            "5) Urbanism/permitting status if terrace/extension/regularisation is relevant<br/>"
            "6) Windows / double glazing condition and street-facing noise exposure<br/>"
            "7) Parking options (private spot / permit rules) + bike storage<br/>"
            "8) Availability date + any required documents for the visit (ID, proof of funds, etc.)<br/>"
            "Thank you."
        )

    # ----------------------------
    # PAGE 0 — Cover upgrade
    # ----------------------------
    story.append(Paragraph(f"Relocation Brief — {city_clean}", styles["Title"]))
    story.append(Paragraph("A practical, street-aware shortlist and action plan for relocating to Brussels.", styles["Subtitle"]))

    # Snapshot (compact, consulting cover)
    snapshot_pairs: List[List[str]] = []
    for k, label in [
        ("budget_buy", "Budget (buy)"),
        ("budget_rent", "Budget (rent)"),
        ("housing_type", "Target"),
        ("bedrooms", "Bedrooms"),
        ("family", "Household"),
        ("priorities", "Priorities"),
        ("must_haves", "Must-haves"),
    ]:
        v = _clean_text(answers.get(k, ""))
        if v:
            snapshot_pairs.append([label, v])
    if snapshot_pairs:
        story.append(_section_title("Client profile (snapshot)", styles))
        story.append(_card([
            _kv_table(snapshot_pairs, styles, col_widths=[3.0 * cm, page_w - 3.0 * cm - 16]),
            Paragraph("Audience fit: built for your current household (Couple) with an optional family lens (schools/childcare) if needed.", styles["Small"]),
        ], padding=8))
        story.append(Spacer(1, 6))

    story.append(_section_title("What you get in this report (in 60 seconds)", styles))
    what_you_get = [
        "Top-3 communes (with microhood “search zones” you can use on portals immediately).",
        "A 7–10 day viewing plan + a scorecard to make decisions faster.",
        "Copy-paste templates (messages + questions) for agents and viewings.",
        "Brussels-specific pitfalls & due diligence checklist (buying basics).",
    ]
    story.append(_card([_bullets(what_you_get, styles["Bullet"])], padding=8))
    story.append(Spacer(1, 8))

    story.append(_section_title("How to use this report (7-day plan)", styles))
    plan = [
        "<b>Day 1 — Setup (60–90 min):</b> create 3 portal searches, save 12 listings, send the message template.",
        "<b>Days 2–5 — Viewings:</b> aim 4–6 viewings; fill the scorecard after each (3–5 min).",
        "<b>Days 6–7 — Decision:</b> 2 final viewings in top pockets; request documents early; prep offer with agent/notary.",
    ]
    story.append(_card([_bullets(plan, styles["Bullet"])], padding=8))
    story.append(Spacer(1, 8))

    story.append(_section_title("Fast promise", styles))
    promise = [
        "After 6–8 viewings, you should have a clear top commune + top microhood type.",
        "A realistic view of trade-offs (parking vs space vs commute).",
        "A shortlist of 1–3 properties worth moving forward on.",
    ]
    story.append(_card([_bullets(promise, styles["Bullet"])], padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGE 1 — One-page Action Plan (most important)
    # ----------------------------
    story.append(_section_title("One-page action plan", styles))

    districts = [d for d in (brief.get("top_districts") or []) if isinstance(d, dict)]
    top3 = districts[:3]

    short_rows = []
    for i, d in enumerate(top3, 1):
        name = _clean_text(d.get("name", "—"))
        why = _truncate(_one_liner_from_commune(d), 120)
        short_rows.append([Paragraph(f"<b>{i}) {name}</b>", styles["Body"]), Paragraph(why, styles["Body"])])

    if short_rows:
        t = Table(short_rows, colWidths=[4.2 * cm, page_w - 4.2 * cm - 16], hAlign="LEFT", splitByRow=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, BG_SOFT]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, STROKE),
        ]))
        story.append(_card([Paragraph("<b>Your Top-3 shortlist</b>", styles["Body"]), t], padding=8))
        story.append(Spacer(1, 6))

    tomorrow_steps = [
        "Create 3 portal searches (Immoweb; optionally also Zimmo).",
        "Pick 12 candidates (4 per commune) and tag: Must-see / Maybe / Reject.",
        "Send the pre-viewing message template to all Must-see listings.",
        "Book 3–5 viewings (aim for 8 total across the week).",
        "After each viewing: fill the scorecard (3–5 minutes).",
    ]
    left = _card([Paragraph("<b>Tomorrow checklist (30–90 minutes)</b>", styles["Body"]), _numbered_table(tomorrow_steps, styles, width=col_w - 16)], padding=8, width=col_w)
    links = [_format_link(x) if isinstance(x, dict) else _clean_text(x) for x in _portal_links()]
    right = _card([Paragraph("<b>Fast links</b>", styles["Body"]), _numbered_table(links[:5], styles, width=col_w - 16)], padding=8, width=col_w)
    story.append(_two_col_grid(left, right, gap=col_gap))
    story.append(Spacer(1, 6))

    story.append(_card([Paragraph("<b>Pre-viewing message template (copy-paste)</b>", styles["Body"]),
                        Paragraph(_clean_text(_pre_view_message_template()), styles["Body"])], padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGE 2 — Trust & Method
    # ----------------------------
    story.append(_section_title("Trust & method", styles))

    trust_blocks: List[Any] = []
    trust_blocks.append(Paragraph("<b>Sources & freshness</b>", styles["Body"]))
    trust_blocks.append(_bullets(_sources_block() + [f"Last updated: {date.today().strftime('%d %b %Y')}"], styles["Bullet"]))
    trust_blocks.append(Spacer(1, 4))
    trust_blocks.append(Paragraph("<b>What is a “microhood” here?</b>", styles["Body"]))
    trust_blocks.append(Paragraph(
        "A microhood is a search zone around anchors / commonly used area labels on portals — not an administrative boundary. "
        "Names and boundaries may vary by portal and locals.", styles["Body"]
    ))
    trust_blocks.append(Spacer(1, 4))
    trust_blocks.append(Paragraph("<b>Scoring explained</b>", styles["Body"]))
    trust_blocks.append(_bullets([
        "5/5 = consistently strong across most pockets; 3/5 = mixed; 1/5 = rarely fits.",
        "Scores are directional: always validate street-by-street and building-by-building.",
    ], styles["Bullet"]))
    trust_blocks.append(Paragraph("<b>What can be wrong (limitations)</b>", styles["Body"]))
    trust_blocks.append(_bullets([
        "Street feel and noise are highly street-dependent; validate in person (day + evening).",
        "Listings can hide humidity/insulation issues; rely on EPC + window quality + smell checks.",
        "Supply changes weekly; treat this shortlist as a weekly-refreshed starting point.",
    ], styles["Bullet"]))
    trust_blocks.append(Spacer(1, 4))
    trust_blocks.append(Paragraph("Microhood names are search labels; always cross-check using portal keywords + anchors.", styles["Body"]))
    trust_blocks.append(Spacer(1, 4))

    trust_blocks.append(Paragraph("<b>Assumptions used for this run</b>", styles["Body"]))
    trust_blocks.extend(_assumptions_block())

    story.append(_card(trust_blocks, padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGE 3 — Executive summary (smarter table)
    # ----------------------------
    story.append(_section_title("Executive summary (quick scan)", styles))
    exec_rows: List[List[Any]] = []
    for d in top3:
        name = _clean_text(d.get("name", "—"))
        best_for_raw = " · ".join(_safe_list(d.get("strengths") or d.get("why") or [], max_n=2))
        watch_raw = " · ".join(_safe_list(d.get("tradeoffs") or d.get("watch_out") or [], max_n=2))
        best_for = _truncate(best_for_raw, 105) or "—"
        watch = _truncate(watch_raw, 95) or "—"

        # Anchors with hints (standardised for quick scan)
        anchors: List[str] = []
        microhoods_raw = [mh for mh in (d.get("microhoods") or []) if isinstance(mh, dict)]

        # Enforce City of Brussels consistency (Option A: centre/Sablon-compatible)
        if re.search(r"\b(city of brussels|brussels city)\b", name.lower()):
            has_north = any(re.search(r"\b(laeken|mutsaard|domaine)\b", _clean_text(m.get("name","")).lower()) for m in microhoods_raw)
            if has_north or not microhoods_raw:
                microhoods_raw = [
                    {"name": "Sablon / Royal Quarter", "why": "boutique streets, parks, museums; strong central resale"},
                    {"name": "Sainte-Catherine / Dansaert", "why": "dining + canal vibe; walkable core"},
                    {"name": "Royal Quarter / Parc de Bruxelles", "why": "green pocket by institutions; calmer evenings"},
                ]

        for mh in microhoods_raw[:3]:
            nm = _clean_text(mh.get("name", ""))
            hint = _clean_text(mh.get("why", ""))
            if nm:
                if hint:
                    anchors.append(f"{_truncate(nm, 32)} — {_truncate(hint, 52)}")
                else:
                    anchors.append(_truncate(nm, 40))

        anchors_txt = "<br/>".join([_clean_text(a) for a in anchors]) if anchors else "—"


        price_line = ""
        br = _split_budget_reality(_clean_text(d.get("budget_reality", "")))
        if br:
            price_line = _truncate(br[0].replace("Rule of thumb:", "").strip(), 85)
        price_line = price_line or "Validate price & charges street-by-street."

        exec_rows.append([
            Paragraph(f"<b>{name}</b>", styles["Body"]),
            Paragraph(best_for, styles["Body"]),
            Paragraph(watch, styles["Body"]),
            Paragraph(anchors_txt, styles["Body"]),
            Paragraph(price_line, styles["Body"]),
        ])

    hdr = [
        Paragraph("<b>Commune</b>", styles["Small"]),
        Paragraph("<b>Best for</b>", styles["Small"]),
        Paragraph("<b>Watch-outs</b>", styles["Small"]),
        Paragraph("<b>Microhood anchors</b>", styles["Small"]),
        Paragraph("<b>Price reality</b>", styles["Small"]),
    ]
    col_ws = [80, 150, 135, 135, max(60, page_w - 80 - 150 - 135 - 135 - 16)]
    tbl = Table([hdr] + exec_rows, colWidths=col_ws, hAlign="LEFT", splitByRow=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BG_SOFT),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, STROKE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(_card([tbl], padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGES 4–6 — Commune cards (1 page each, stable caps)
    # ----------------------------
    def _microhood_mini_cards(microhoods: List[Dict[str, Any]]) -> Any:
        """Render microhoods as mini-cards: name + keywords/anchors/hints/avoid.

        Enforces a stable schema for auto-generated content:
        - portal_keywords: list, len>=2
        - anchors: list, len>=2
        - street_hints: exactly 2 short bullets
        - avoid_verify: 1 specific bullet
        """
        def _norm_name(n: str) -> str:
            n = _clean_text(n)
            # Normalise spaces around hyphens (Saint - Pierre -> Saint-Pierre)
            n = re.sub(r"\s*-\s*", "-", n)
            return n

        def _one_line(n: str, max_len: int = 34) -> str:
            n = _norm_name(n)
            if len(n) > max_len:
                n = n[: max_len - 1].rstrip() + "…"
            # Prevent internal wraps inside the name
            return f"<nobr>{n}</nobr>"

        def _ensure_list(val: Any) -> List[str]:
            if val is None:
                return []
            if isinstance(val, str):
                return [_clean_text(val)]
            if isinstance(val, list):
                return [_clean_text(x) for x in val if _clean_text(x)]
            return []

        cards: List[List[Any]] = []
        for mh in (microhoods or [])[:4]:
            if not isinstance(mh, dict):
                continue

            name_raw = mh.get("name", "") or "—"
            name = _one_line(name_raw)

            # --- Schema upgrade / fallbacks ---
            pkw = _ensure_list(mh.get("portal_keywords") or mh.get("keywords"))
            # Add name variants
            base = _norm_name(name_raw)
            if base and base not in pkw:
                pkw.insert(0, base)
            if base and base.replace("-", " ") not in pkw:
                pkw.append(base.replace("-", " "))
            pkw = [x for x in pkw if x][:4]
            if len(pkw) < 2 and base:
                pkw = [base, base.replace("-", " ")]

            anchors = _ensure_list(mh.get("anchors") or mh.get("anchor_points"))
            if len(anchors) < 2:
                # try to infer from name/nearby
                anchors = anchors[:1] + [f"Near {base}"] if base else (anchors + ["—"])
            anchors = anchors[:2]

            hints = _ensure_list(mh.get("street_hints"))
            if len(hints) < 2:
                why = _clean_text(mh.get("why", "")) or ""
                # Split long why into two hints if possible
                if why and (";" in why or "." in why):
                    parts = re.split(r"[.;]\s+", why)
                    parts = [p.strip() for p in parts if p.strip()]
                    hints = (parts + hints)[:2]
                elif why:
                    hints = [why, "Prefer calm side streets 1–2 blocks off major axes."]
                else:
                    hints = ["Prefer calm side streets 1–2 blocks off major axes.", "Validate evening noise and delivery traffic."]

            hints = [_truncate(h, 80) for h in hints[:2]]
            # Defensive: ensure we always have exactly 2 hints (auto-generated content can be incomplete)
            if len(hints) < 2:
                defaults = [
                    "Prefer calm side streets 1–2 blocks off major axes.",
                    "Validate evening noise and delivery traffic.",
                ]
                for d in defaults:
                    if len(hints) >= 2:
                        break
                    if d not in hints:
                        hints.append(_truncate(d, 80))

            avoid = _clean_text(mh.get("avoid_verify") or mh.get("avoid") or mh.get("watch_out") or mh.get("risk") or "")
            avoid = re.sub(r"^What to check:\s*", "", avoid, flags=re.I)
            avoid = re.sub(r"^Check:\s*", "", avoid, flags=re.I)
            if not avoid:
                avoid = "Direct frontage on main arteries; verify window quality and night noise."
            avoid = _truncate(avoid, 110)

            details = "<br/>".join([
                f"<font color='{TEXT_MUTED.hexval()}'>Portal keywords:</font> {', '.join([_truncate(x, 26) for x in pkw])}",
                f"<font color='{TEXT_MUTED.hexval()}'>Anchors:</font> {'; '.join([_truncate(x, 34) for x in anchors if x])}",
                f"<font color='{TEXT_MUTED.hexval()}'>Street hints:</font> • {hints[0]} • {hints[1]}",
                f"<font color='{TEXT_MUTED.hexval()}'>Avoid/verify:</font> • {avoid}",
            ])

            cards.append([
                Paragraph(f"<b>{name}</b>", styles["Body"]),
                Paragraph(details, styles["Body"]),
            ])

        if not cards:
            return Paragraph("—", styles["Body"])

        t = Table(cards, colWidths=[3.8 * cm, page_w - 3.8 * cm - 16], hAlign="LEFT", splitByRow=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("INNERGRID", (0, 0), (-1, -1), 0.45, STROKE),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, BG_SOFT]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    for i, d in enumerate(top3, 1):
        name = _clean_text(d.get("name", "—"))
        story.append(_section_title(f"{i}. {name}", styles))
        # A compact "profile" line: anchors + chips
        anchors = ", ".join([_clean_text(a) for a in (d.get("micro_anchors") or [])[:3] if _clean_text(a)])
        if anchors:
            story.append(Paragraph(f"<font color='{TEXT_MUTED.hexval()}'>Anchors:</font> {anchors}", styles["Small"]))
        chips = _chips(d.get("scores") or {}, styles, ["Family", "Commute", "Lifestyle", "BudgetFit", "Overall"])
        if chips:
            story.append(chips)
            story.append(Spacer(1, 4))

        why_bullets = _safe_list(d.get("why") or d.get("strengths") or [], max_n=3)
        if not why_bullets:
            why_bullets = _safe_list(d.get("strengths") or [], max_n=3)
        trade = _safe_list(d.get("tradeoffs") or d.get("watch_out") or [], max_n=6)

        # Market reality: short + honest (no magic numbers)
        budget_lines = _split_budget_reality(_clean_text(d.get("budget_reality", "")))
        budget_lines = [_truncate(x, 150) for x in budget_lines][:2]

        commune_blocks: List[Any] = []
        commune_blocks.append(Paragraph("<b>Why this commune</b>", styles["Body"]))
        commune_blocks.append(_bullets([_truncate(x, 150) for x in why_bullets], styles["Bullet"]))
        commune_blocks.append(Spacer(1, 3))
        if budget_lines:
            commune_blocks.append(Paragraph("<b>Price reality</b>", styles["Body"]))
            commune_blocks.append(_bullets(budget_lines, styles["Bullet"]))
            commune_blocks.append(Spacer(1, 3))

        commune_blocks.append(Paragraph("<b>Microhood shortlist (search zones)</b>", styles["Body"]))
        microhoods_raw = [mh for mh in (d.get("microhoods") or []) if isinstance(mh, dict)]
        if re.search(r"\b(city of brussels|brussels city)\b", _clean_text(d.get("name","")).lower()):
            has_north = any(re.search(r"\b(laeken|mutsaard|domaine)\b", _clean_text(m.get("name","")).lower()) for m in microhoods_raw)
            if has_north or not microhoods_raw:
                microhoods_raw = [
                    {"name": "Sablon / Royal Quarter", "why": "boutique streets, parks, museums; strong central resale"},
                    {"name": "Sainte-Catherine / Dansaert", "why": "dining + canal vibe; walkable core"},
                    {"name": "Royal Quarter / Parc de Bruxelles", "why": "green pocket by institutions; calmer evenings"},
                ]
        commune_blocks.append(_microhood_mini_cards(microhoods_raw))
        commune_blocks.append(Spacer(1, 3))

        if trade:
            commune_blocks.append(Paragraph("<b>Trade-offs to watch (Brussels-specific)</b>", styles["Body"]))
            commune_blocks.append(_bullets([_truncate(x, 150) for x in trade[:6]], styles["Bullet"]))

        story.append(_card(commune_blocks, padding=8))
        if i < len(top3):
            story.append(PageBreak())

    # ----------------------------
    # PAGE 7 — Viewing plan + Scorecard
    # ----------------------------
    story.append(PageBreak())
    story.append(_section_title("Viewing plan + scorecard", styles))
    story.append(Paragraph("<b>Property / address:</b> _________&nbsp;&nbsp;&nbsp;&nbsp; <b>Microhood / commune:</b> _________", styles["Body"]))
    story.append(Spacer(1, 4))

    plan_lines = [
        "Aim: 8 viewings total (3 + 3 + 2 across the communes).",
        "Fill the scorecard right after each viewing (3–5 minutes).",
        "Shortlist 1–3 properties for a second visit in your top pocket(s).",
    ]
    story.append(_card([_bullets(plan_lines, styles["Bullet"])], padding=8))
    story.append(Spacer(1, 6))

    # Scorecard table (1–5 fields + notes)
    headers = ["Viewing", "Noise", "Light", "EPC", "Charges", "Parking", "Commute", "Kids", "Resale", "Gut"]
    rows = [headers]
    for r in range(1, 9):
        rows.append([str(r), "□", "□", "□", "□", "□", "□", "□", "□", "□"])

    score_tbl = Table(rows, hAlign="LEFT", colWidths=[1.2*cm] + [ (page_w-1.2*cm-16)/9.0 ]*9)
    score_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BG_SOFT),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, STROKE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(_card([Paragraph("<b>Scorecard (1–5 or tick boxes)</b>", styles["Body"]), score_tbl,
                        Paragraph("<font color='{0}'>Tip:</font> 5 = excellent, 3 = mixed, 1 = poor. Resale = ease of selling later (street quality + building health + liquidity). Add a short note in your own doc after each viewing.".format(TEXT_MUTED.hexval()), styles["Small"])],
                       padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGE 8 — Questions to ask
    # ----------------------------
    story.append(_section_title("Questions to ask (copy-paste)", styles))

    before = [
        "Please confirm in writing and share documents where possible (EPC, electrical, syndic pack).",
        "EPC rating and heating type? Any planned works in the building?",
        "Monthly charges (syndic/HOA) and what's included? Reserve fund amount + planned works list (if apartment).",
        "Parking options (private spot / permit) and bike storage?",
        "Noise exposure: which side faces the street; double glazing?",
        "Any urbanism/permit constraints (extensions/terraces) if relevant?",
    ]
    during = [
        "Check street noise at the windows (open/closed) and at peak hours if possible.",
        "Test water pressure, heating, and ventilation; check humidity/mold signs.",
        "Ask for electrical report + verify consumer unit / grounding.",
        "Confirm insulation and windows; note orientation and natural light.",
        "Look for cellar/storage, stroller access, elevator, bike room.",
    ]
    offer = [
        "Request documents early: EPC, electrical, urbanism (if needed), syndic docs, minutes, budget.",
        "Clarify conditions in the offer (financing, technical inspection, document receipt).",
        "Plan timeline: offer → compromis → deed (notary) and move-in date alignment.",
    ]

    story.append(_two_col_grid(
        _card([Paragraph("<b>Before viewing</b>", styles["Body"]), _bullets(before, styles["Bullet"])], padding=8, width=col_w),
        _card([Paragraph("<b>During viewing</b>", styles["Body"]), _bullets(during, styles["Bullet"])], padding=8, width=col_w),
        gap=col_gap,
    ))
    story.append(Spacer(1, 6))
    story.append(_card([Paragraph("<b>Offer stage (Belgium specifics)</b>", styles["Body"]), _bullets(offer, styles["Bullet"])], padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGE 9 — Belgium buying basics + Brussels pitfalls
    # ----------------------------
    story.append(_section_title("Belgium buying basics (compact)", styles))
    basics = [
        "Typical flow: offer → compromis (sale agreement) → deed at notary (timing varies).",
        "Key docs: EPC, electrical inspection, urbanism/permit notes (if applicable).",
        "If apartment: syndic/HOA docs (charges, reserve fund, minutes, planned works).",
        "Registration fees & notary costs: factor them early (details depend on region and situation).",
        "Budget buffer: keep a margin for first-year fixes (windows, heating, humidity).",
    ]
    pitfalls = [
        "If apartment: planned works can override “cheap charges”; always ask for minutes + budget + reserve fund.",
        "Noise on main arteries: validate street-by-street; avoid assuming the whole commune is quiet.",
        "Parking reality: permits vs private spots; check rules for the exact address.",
        "Old building trade-offs: EPC, insulation, humidity; ask about recent works.",
        "Syndic charges can vary widely; validate what's included and reserve fund health.",
        "Orientation/light: same street can be night/day difference; check sunlight in person.",
        "Schools/childcare: availability and waitlists; start inquiries early if relevant.",
        "Public transport nodes: great convenience but can mean higher noise/foot traffic.",
        "Renovations: confirm permits and restrictions for terraces/extensions if important to you.",
    ]
    story.append(_card([Paragraph("<b>Buying basics</b>", styles["Body"]), _bullets(basics, styles["Bullet"]),
                        Spacer(1, 3),
                        Paragraph("<b>Brussels-specific pitfalls (quick list)</b>", styles["Body"]), _bullets(pitfalls, styles["Bullet"])],
                       padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGE 10 — Settling-in (shortened essentials + providers)
    # ----------------------------
    story.append(_section_title("Settling-in essentials (short)", styles))
    rel = brief.get("relocation_essentials") or {}
    # Commune registration (typical minimum docs)
    reg_docs = [
        "Passport/ID + residence documents (if applicable)",
        "Proof of address (lease / deed / housing attestation)",
        "Civil status docs if relevant (marriage/birth) — originals + copies",
        "Work proof (contract/employer letter) if requested",
    ]
    story.append(_card([
        Paragraph("<b>Commune registration — typical minimum</b>", styles["Body"]),
        Paragraph("<font color='{0}'>Where to start:</font> IRISbox (Brussels region) and your commune appointment page.".format(TEXT_MUTED.hexval()), styles["Small"]),
        _bullets(reg_docs, styles["Bullet"]),
    ], padding=8))
    story.append(Spacer(1, 6))

    first_72 = _safe_list(rel.get("first_72h"), max_n=3)
    first_2w = _safe_list(rel.get("first_2_weeks"), max_n=3)
    first_2m = _safe_list(rel.get("first_2_months"), max_n=3)

    providers = [
        "<b>Mobile:</b> Proximus / Orange / Telenet — compare coverage where you live.",
        "<b>Internet:</b> Proximus / Telenet — check fiber/cable availability by address.",
        "<b>Energy:</b> Engie / Luminus — compare fixed vs variable, contract terms.",
    ]
    school = [
        "School/childcare types: communal (FR/NL) vs international/private (budget-dependent).",
        "Waitlists exist: prepare documents early (ID, proof of address, vaccinations if required).",
    ]

    left = _card([Paragraph("<b>First 72 hours</b>", styles["Body"]), _bullets(first_72 or ["—"], styles["Bullet"]),
                  Spacer(1, 3),
                  Paragraph("<b>First 2 weeks</b>", styles["Body"]), _bullets(first_2w or ["—"], styles["Bullet"])],
                 padding=8, width=col_w)
    right = _card([Paragraph("<b>First 2 months</b>", styles["Body"]), _bullets(first_2m or ["—"], styles["Bullet"])], padding=8, width=col_w)
    story.append(_two_col_grid(left, right, gap=col_gap))
    story.append(Spacer(1, 6))
    story.append(_card([Paragraph("<b>Providers (quick shortlist)</b>", styles["Body"]), _bullets(providers, styles["Bullet"]),
                        Spacer(1, 3),
                        Paragraph("<b>Schools & childcare</b>", styles["Body"]), _bullets(school, styles["Bullet"])],
                       padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGE 11 — Agencies & resources (clean numbered tables)
    # ----------------------------
    story.append(_section_title("Agencies and resources", styles))
    story.append(Paragraph("Curated starting points for Belgium/Brussels.", styles["Small"]))
    story.append(_card([
        Paragraph("<b>How to choose an agent (quick criteria)</b>", styles["Body"]),
        _bullets([
            "Local focus: ask which communes they personally cover weekly.",
            "Deal type: apartments vs houses — relevant track record.",
            "Responsiveness: same-day replies and WhatsApp support.",
            "Due diligence: habits around syndic pack / EPC / urbanism.",
            "Negotiation: ask for 2 recent anonymized deal examples.",
        ], styles["Bullet"]),
    ], padding=8))
    story.append(Spacer(1, 6))
    story.append(_card([
        Paragraph("<b>Recommended outreach order</b>", styles["Body"]),
        _bullets([
            "Start with 2 local agents + 1 network office per commune.",
            "Compare answer quality within 48 hours (docs, clarity, speed).",
        ], styles["Bullet"]),
    ], padding=8))
    story.append(Spacer(1, 6))

    agencies = [a for a in (brief.get("agencies") or []) if isinstance(a, dict)]
    websites = [w for w in (brief.get("real_estate_sites") or []) if isinstance(w, dict)]

    left_block = _card([Paragraph("<b>Agencies</b>", styles["Body"]),
                        _numbered_table([_format_link(x) for x in agencies[:5]], styles, width=col_w - 16)], padding=8, width=col_w)
    right_block = _card([Paragraph("<b>Websites</b>", styles["Body"]),
                         _numbered_table([_format_link(x) for x in websites[:3]], styles, width=col_w - 16)], padding=8, width=col_w)
    story.append(_two_col_grid(left_block, right_block, gap=col_gap))

    doc.build(
        story,
        onFirstPage=lambda c, d: _header_footer(c, d, f"Relocation Brief — {city_clean}"),
        onLaterPages=lambda c, d: _header_footer(c, d, f"Relocation Brief — {city_clean}"),
    )
