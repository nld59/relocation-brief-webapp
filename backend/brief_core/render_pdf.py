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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
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
TEXT = colors.HexColor('#111827')


def _ensure_fonts_registered() -> None:
    """Register a Unicode-capable font.

    We rely on a non-breaking hyphen (U+2011) to avoid ugly one-letter wraps in
    hyphenated microhood names. Base PDF fonts (Helvetica) often don't support
    this glyph, which shows up as black squares.
    """
    try:
        pdfmetrics.getFont("DejaVuSans")
        return
    except Exception:
        pass

    # DejaVu is available on most Linux distros.
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
        # Ensure ReportLab can resolve <b> tags to the correct bold face.
        pdfmetrics.registerFontFamily(
            "DejaVuSans",
            normal="DejaVuSans",
            bold="DejaVuSans-Bold",
            italic="DejaVuSans",
            boldItalic="DejaVuSans-Bold",
        )
    except Exception:
        # Fallback: keep built-in fonts. In this case, we must not emit U+2011.
        return

# Displayed in footer for easier iteration and client support.
REPORT_VERSION = "v11.0"


def _truncate(text: Any, max_chars: int) -> str:
    """Truncate for summary tables, preferring sentence/phrase boundaries."""
    t = _clean_text(text)
    if len(t) <= max_chars:
        return t

    # Prefer cutting on a sentence boundary ('.' or '•' or '—') within range.
    window = t[: max_chars].rstrip()
    # Find a nice breakpoint close to the end.
    for sep in (".", "•", "—", ";"):
        idx = window.rfind(sep)
        if idx >= max(0, len(window) - 45):  # near the end
            candidate = window[: idx + (1 if sep == "." else 0)].rstrip()
            if len(candidate) >= 20:
                return candidate.rstrip(" ,.;:") + "…"

    # Fallback: word boundary.
    cut = t[: max_chars - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


def _nb_hyphen(s: str) -> str:
    """Prevent ugly wraps in hyphenated names.

    Replace ASCII hyphens between word characters with a non-breaking hyphen.
    Example: "Brugmann-Lepoutre" will not wrap as "Brugmann-Lepoutr / e".
    """
    s = _clean_text(s)
    return re.sub(r"(?<=\w)-(?=\w)", "\u2011", s)


def _clean_text(s: Any) -> str:
    if s is None:
        return ""
    s = str(s)
    # Keep the PDF stable (avoid curly quotes / NBSP) and common punctuation artifacts.
    # Normalize weird no-break spaces / joiners that can render as black squares.
    s = (
        s.replace("\u00A0", " ")  # nbsp
        .replace("\u202F", " ")  # narrow nbsp
        .replace("\u2007", " ")  # figure space
        .replace("\u2060", "")   # word-joiner
        .replace("\u200B", "")   # zero-width space
        .replace("\ufeff", "")   # BOM
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
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
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


def _compact_price_for_summary(price_text: str) -> str:
    """Compact long numeric ranges specifically for the Executive summary table.
    Keeps tokens together to reduce ugly wraps in narrow cells.
    Examples:
      €490,000–€1,240,000 -> €490k–€1.24m
    """
    if not price_text:
        return ""
    t = str(price_text)
    # normalize dash variants
    t = t.replace("—", "–").replace("-", "–")
    # compact common Euro ranges: €490,000–€1,240,000  ->  €490k–€1.24m
    import re
    def _fmt_num(n: str) -> str:
        try:
            val = float(n.replace(",", ""))
        except Exception:
            return n
        if val >= 1_000_000:
            return f"{val/1_000_000:.2f}".rstrip("0").rstrip(".") + "m"
        if val >= 1_000:
            return f"{val/1_000:.0f}" + "k"
        return str(int(val))
    # replace sequences like €490,000–€1,240,000
    def repl(m):
        a, b = m.group(1), m.group(2)
        return f"€{_fmt_num(a)}–€{_fmt_num(b)}"
    t = re.sub(r"€\s*([0-9][0-9,]*)\s*–\s*€\s*([0-9][0-9,]*)", repl, t)
    # prevent splitting currency token: add NBSP after €
    t = t.replace("€", "€\u00A0")
    return t


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

    def _household_label(a: Dict[str, Any]) -> str:
        # Accept multiple intake schemas (household, family, children_count, etc.)
        h = _clean_text(str(a.get('household') or a.get('household_type') or a.get('family') or '')).lower()
        kids_raw = a.get('children_count', a.get('kids_count', a.get('children', a.get('kids', 0))))
        try:
            kids_n = int(kids_raw) if str(kids_raw).strip() else 0
        except Exception:
            kids_n = 0

        if 'family' in h or kids_n > 0:
            return f"Family ({kids_n} child{'ren' if kids_n != 1 else ''})" if kids_n else 'Family'
        if 'couple' in h or 'partner' in h:
            return 'Couple'
        if 'single' in h:
            return 'Single'
        return 'Household'

    household_label = _household_label(answers)
    audience_fit_line = f"Audience fit: built for your current household ({household_label})."


    # ---------- Fonts (Unicode-safe) ----------
    # We use Unicode characters (e.g., non-breaking hyphen \u2011) to prevent
    # ugly wraps in hyphenated names. Base Helvetica may render those as boxes,
    # so we register DejaVuSans which covers the needed glyphs.
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
        # Ensure <b> resolves to our bold face (otherwise ReportLab may fall back
        # to Helvetica-Bold, which can render some unicode as □).
        pdfmetrics.registerFontFamily(
            "DejaVuSans",
            normal="DejaVuSans",
            bold="DejaVuSans-Bold",
            italic="DejaVuSans",
            boldItalic="DejaVuSans-Bold",
        )
        FONT_REGULAR = "DejaVuSans"
        FONT_BOLD = "DejaVuSans-Bold"
    except Exception:
        # Fallback for environments without those fonts.
        FONT_REGULAR = "Helvetica"
        FONT_BOLD = "Helvetica-Bold"

    # ---------- Styles ----------
    styles_src = getSampleStyleSheet()
    base_normal = styles_src['Normal']
    base_h1 = styles_src['Heading1'] if 'Heading1' in styles_src else styles_src['Title']
    base_h2 = styles_src['Heading2'] if 'Heading2' in styles_src else styles_src['Heading1']

    styles: Dict[str, ParagraphStyle] = {
        'Normal': ParagraphStyle(
            'Normal', parent=base_normal, fontName=FONT_REGULAR, boldFontName=FONT_BOLD,
            fontSize=10, leading=12, textColor=TEXT
        ),
        'Small': ParagraphStyle(
            'Small', parent=base_normal, fontName=FONT_REGULAR, boldFontName=FONT_BOLD,
            fontSize=9, leading=11, textColor=TEXT
        ),
        'Muted': ParagraphStyle(
            'Muted', parent=base_normal, fontName=FONT_REGULAR, boldFontName=FONT_BOLD,
            fontSize=9, leading=11, textColor=TEXT_MUTED
        ),
        'H1': ParagraphStyle(
            'H1', parent=base_h1, fontName=FONT_BOLD, boldFontName=FONT_BOLD,
            fontSize=18, leading=22, textColor=TEXT
        ),
        'H2': ParagraphStyle(
            'H2', parent=base_h2, fontName=FONT_BOLD, boldFontName=FONT_BOLD,
            fontSize=13, leading=16, spaceBefore=10, spaceAfter=6, textColor=TEXT
        ),
        'CardTitle': ParagraphStyle(
            'CardTitle', parent=base_normal, fontName=FONT_BOLD, boldFontName=FONT_BOLD,
            fontSize=12, leading=14, textColor=TEXT, spaceAfter=2
        ),
        'CardSub': ParagraphStyle(
            'CardSub', parent=base_normal, fontName=FONT_REGULAR, boldFontName=FONT_BOLD,
            fontSize=9.5, leading=11.5, textColor=TEXT_MUTED, spaceAfter=4
        ),
        'Bullet': ParagraphStyle(
            'Bullet', parent=base_normal, fontName=FONT_REGULAR, boldFontName=FONT_BOLD,
            fontSize=10, leading=12, leftIndent=12, bulletIndent=0, spaceBefore=2, spaceAfter=2, textColor=TEXT
        ),
        'ExecHdr': ParagraphStyle(
            'ExecHdr', parent=base_normal, fontName=FONT_BOLD, boldFontName=FONT_BOLD,
            fontSize=9, leading=10.5, textColor=TEXT, alignment=1, spaceAfter=0
        ),
        'ExecCell': ParagraphStyle(
            'ExecCell', parent=base_normal, fontName=FONT_REGULAR, boldFontName=FONT_BOLD,
            fontSize=9, leading=10.5, textColor=TEXT, spaceAfter=0
        ),
        'ExecCellMuted': ParagraphStyle(
            'ExecCellMuted', parent=base_normal, fontName=FONT_REGULAR, boldFontName=FONT_BOLD,
            fontSize=9, leading=10.5, textColor=TEXT_MUTED, spaceAfter=0
        ),
    }
    # Backwards-compatible aliases used across the file
    styles['Title'] = styles['H1']
    styles['Subtitle'] = ParagraphStyle(
        'Subtitle', parent=styles['Muted'], fontName=FONT_REGULAR, fontSize=11, leading=14, textColor=TEXT_MUTED
    )
    styles['Body'] = styles['Normal']



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
            Paragraph(audience_fit_line, styles["Small"]),
        ], padding=8))
        story.append(Spacer(1, 6))

    story.append(_section_title("What you get in this report (in 60 seconds)", styles))
    what_you_get = [
        "Top-3 communes (with microhood “search zones” you can use on portals immediately).",
        "A 7–10 day viewing plan + a simple note template to make decisions faster.",
        "Copy-paste templates (messages + questions) for agents and viewings.",
        "Brussels-specific pitfalls & due diligence checklist (buying basics).",
    ]
    story.append(_card([_bullets(what_you_get, styles["Bullet"])], padding=8))
    story.append(Spacer(1, 8))

    story.append(_section_title("How to use this report (7-day plan)", styles))
    plan = [
        "<b>Day 1 — Setup (60–90 min):</b> create 3 portal searches, save 12 listings, send the message template.",
        "<b>Days 2–5 — Viewings:</b> aim 4–6 viewings; write quick notes after each (3–5 min).",
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
        "After each viewing: write quick notes (3–5 minutes).",
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
    # PAGE 2 — Executive summary (quick scan)
    # ----------------------------
    story.append(_section_title("Executive summary (quick scan)", styles))

    usable_w = page_w - 16  # account for card padding
    col_ws = [
        usable_w * 0.18,
        usable_w * 0.26,
        usable_w * 0.24,
        usable_w * 0.32,
    ]

    # NOTE: Executive summary must never cut sentences mid-way.
    # We let cells grow vertically and compute row heights from Paragraph wraps.
    def _fit_exec_sentence(text: str, *, width: float, max_lines: int = 5) -> str:
        """Ensure executive-summary copy is short AND complete, without ellipsis.

        We try to keep a full clause/sentence. If the provided text is too long
        (wraps into more than `max_lines`), we shorten by taking the first
        sentence / clause, stripping parentheticals, etc.
        """
        t0 = _clean_text(text).replace("…", "").strip()
        if not t0:
            return "—"

        candidates: List[str] = []
        # Original
        candidates.append(t0)
        # Remove parentheticals
        candidates.append(re.sub(r"\s*\([^)]*\)", "", t0).strip())
        # First sentence
        for sep in [".", ";", ":"]:
            if sep in t0:
                candidates.append(t0.split(sep, 1)[0].strip().rstrip(" ,;:") + ".")
        # First comma-clause
        if "," in t0:
            candidates.append(t0.split(",", 1)[0].strip().rstrip(" ,;:") + ".")

        # De-duplicate while preserving order
        seen = set()
        uniq: List[str] = []
        for c in candidates:
            c = c.strip()
            if not c:
                continue
            if not c.endswith((".", "!", "?")):
                c = c.rstrip(" ,;:") + "."
            key = c.lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)

        for c in uniq:
            p = Paragraph(c, styles["ExecCell"])
            _, h = p.wrap(width - 8, 10_000)
            # Convert height to approximate number of lines.
            lines = int(round(h / max(styles["ExecCell"].leading, 1)))
            if lines <= max_lines:
                return c

        # Last resort: keep the shortest complete candidate.
        return min(uniq, key=len) if uniq else "—"
    exec_rows: List[List[Any]] = []
    for row in (brief.get("executive_summary") or [])[:3]:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name", "—"))
        best_for = _fit_exec_sentence(row.get("best_for", "—"), width=col_ws[1])
        watch = _fit_exec_sentence(row.get("watch_out", "—"), width=col_ws[2])
        mhs = [_nb_hyphen(_clean_text(x)) for x in (row.get("top_microhoods") or []) if _clean_text(x)][:2]
        # Top microhoods column must contain only microhood names (no keywords here).
        mh_txt = " · ".join(mhs) if mhs else "—"

        exec_rows.append([
            Paragraph(f"<b>{name}</b>", styles["ExecCell"]),
            Paragraph(best_for, styles["ExecCell"]),
            Paragraph(watch, styles["ExecCell"]),
            Paragraph(mh_txt, styles["ExecCell"]),
        ])

    hdr = [
        Paragraph("<b>Commune</b>", styles["ExecHdr"]),
        Paragraph("<b>Best for</b>", styles["ExecHdr"]),
        Paragraph("<b>Watch-outs</b>", styles["ExecHdr"]),
        Paragraph("<b>Top microhoods</b>", styles["ExecHdr"]),
    ]
    # Dynamic row heights: measure Paragraph wraps so text never truncates.
    data = [hdr] + exec_rows

    def _row_height(r: List[Any], is_header: bool = False) -> float:
        heights = []
        for j, cell in enumerate(r):
            if hasattr(cell, "wrap"):
                _, h = cell.wrap(col_ws[j] - 8, 10_000)  # subtract padding
                heights.append(h)
            else:
                heights.append(styles["ExecCell"].leading)
        base = max(heights) if heights else styles["ExecCell"].leading
        pad = 10 if is_header else 8
        return base + pad

    row_heights = [_row_height(data[0], is_header=True)] + [_row_height(r) for r in data[1:]]
    tbl = Table(data, colWidths=col_ws, rowHeights=row_heights, hAlign="LEFT", splitByRow=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BG_SOFT),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, STROKE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(_card([tbl], padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGE 3 — Trust & Method
    # ----------------------------
    story.append(_section_title("Trust & method", styles))

    trust_blocks: List[Any] = []
    trust_blocks.append(Paragraph("<b>Sources & freshness</b>", styles["Body"]))
    trust_blocks.append(_bullets(_sources_block() + [f"Last updated: {date.today().strftime('%d %b %Y')}"], styles["Bullet"]))
    trust_blocks.append(Spacer(1, 4))
    trust_blocks.append(Paragraph("<b>What is a microhood here?</b>", styles["Body"]))
    trust_blocks.append(Paragraph(
        "A microhood is a practical search zone *inside a commune* (e.g., City of Brussels / Sablon). "
        "Names follow the city-pack microhood list and may differ slightly from portal labels.",
        styles["Body"],
    ))
    trust_blocks.append(Spacer(1, 4))
    trust_blocks.append(Paragraph("<b>Transparent scoring</b>", styles["Body"]))
    trust_blocks.append(_bullets([
        "We compute five scores (Safety, Family, Commute, Lifestyle, BudgetFit) using city-pack signals and your stated budget.",
        "Overall is the rounded average of these five scores, so you can compare communes on one simple number.",
    ], styles["Bullet"]))
    trust_blocks.append(Paragraph("<b>What can be wrong (limitations)</b>", styles["Body"]))
    trust_blocks.append(_bullets([
        "Street feel and noise are highly street-dependent; validate in person (day + evening).",
        "Listings can hide humidity/insulation issues; rely on EPC + window quality + smell checks.",
        "Supply changes weekly; treat this shortlist as a refreshed starting point.",
    ], styles["Bullet"]))
    trust_blocks.append(Spacer(1, 4))
    trust_blocks.append(Paragraph("<b>Assumptions used for this run</b>", styles["Body"]))
    trust_blocks.extend(_assumptions_block())

    story.append(_card(trust_blocks, padding=8))
    story.append(PageBreak())

    # ----------------------------
    # PAGES 4–6 — Commune cards (1 page each, stable caps)
    # ----------------------------
    def _microhood_mini_cards(microhoods: List[Dict[str, Any]]) -> Any:
        """Render microhoods as mini-cards.

        Sprint-2+ schema:
        - portal_keywords: up to 4 tokens (optional, for portal searching)
        - highlights: 2–3 sentences describing what is specific/valuable about this microhood
        """
        def _norm_name(n: str) -> str:
            n = _clean_text(n)
            # Normalise spaces around hyphens (Saint - Pierre -> Saint-Pierre)
            n = re.sub(r"\s*-\s*", "-", n)
            return n

        def _display_name(n: str) -> str:
            # Keep it readable and avoid one-letter wraps for hyphenated names.
            return _nb_hyphen(_norm_name(n))

        def _ensure_list(val: Any) -> List[str]:
            if val is None:
                return []
            if isinstance(val, str):
                return [_clean_text(val)]
            if isinstance(val, list):
                return [_clean_text(x) for x in val if _clean_text(x)]
            return []


        def _dedupe_preserve(items: List[str]) -> List[str]:
            seen = set()
            out: List[str] = []
            for it in items:
                key = it.strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(it)
            return out

        cards: List[List[Any]] = []
        for mh in (microhoods or [])[:4]:
            if not isinstance(mh, dict):
                continue

            name_raw = mh.get("name", "") or "—"
            name = _display_name(name_raw)

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

            highlights = _clean_text(mh.get("highlights") or mh.get("why") or "")
            if not highlights:
                highlights = "Good starting point with balanced everyday amenities."  # safe fallback

            # Do not truncate portal keywords with ellipses; allow natural wrapping.
            details_lines = [
                f"<font color='{TEXT_MUTED.hexval()}'>Portal keywords:</font> {', '.join(pkw)}",
                f"<font color='{TEXT_MUTED.hexval()}'>Highlights:</font> {highlights}",
            ]
            details = "<br/>".join(details_lines)

            cards.append([
                Paragraph(f"<b>{name}</b>", styles["Body"]),
                Paragraph(details, styles["Body"]),
            ])

        if not cards:
            return Paragraph("—", styles["Body"])

        # Make name column slightly wider to avoid ugly wraps on hyphenated names.
        name_w = 4.6 * cm
        t = Table(cards, colWidths=[name_w, page_w - name_w - 16], hAlign="LEFT", splitByRow=1)
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
        # A compact "profile" line: top microhoods + chips
        top_mh = [ _nb_hyphen(_clean_text(x)) for x in (d.get("top_microhoods") or []) if _clean_text(x) ][:2]
        if top_mh:
            story.append(Paragraph(f"<font color='{TEXT_MUTED.hexval()}'>Top microhoods:</font> {' · '.join(top_mh)}", styles["Small"]))
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

        commune_blocks.append(Paragraph("<b>Microhood shortlist (search zones)</b>", styles["Body"]))
        microhoods_raw = [mh for mh in (d.get("microhoods") or []) if isinstance(mh, dict)]
        commune_blocks.append(_microhood_mini_cards(microhoods_raw))
        commune_blocks.append(Spacer(1, 3))

        if trade:
            commune_blocks.append(Paragraph("<b>Trade-offs to watch (Brussels-specific)</b>", styles["Body"]))
            commune_blocks.append(_bullets([_truncate(x, 150) for x in trade[:6]], styles["Bullet"]))

        story.append(_card(commune_blocks, padding=8))
        if i < len(top3):
            story.append(PageBreak())

    # ----------------------------
    

# PAGE 8 — Questions to ask
    # ----------------------------
    story.append(PageBreak())
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
    
    # Second viewing checklist (for shortlisted properties)
    second_view = [
        "Confirm charges breakdown (syndic/HOA) + reserve fund + planned works; get minutes and budget in writing.",
        "Verify heating system, insulation, and any moisture issues (cellar/bathroom corners, ventilation).",
        "Check noise at different times (street, neighbors) and window quality; ask about recent complaints.",
        "Validate parking reality (permit rules, availability, private spots) and storage (bikes/strollers).",
        "Review legal/urbanism points (permits, co-ownership rules) if you plan renovations or terraces.",
        "Ask for a clear inventory of included fixtures/appliances and estimated move-in timeline.",
        "If possible: bring a contractor/inspector for a quick sanity-check of hidden costs.",
    ]
    story.append(Spacer(1, 6))
    story.append(_card([Paragraph("<b>Second viewing checklist (5–10 min)</b>", styles['Body']), _bullets(second_view, styles['Bullet'])], padding=8))

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