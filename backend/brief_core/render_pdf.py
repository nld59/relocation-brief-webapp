from __future__ import annotations

from typing import Dict, Any, List, Tuple
from pathlib import Path
from functools import lru_cache
import json
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors


# base vertical spacing between major blocks
GAP = 0.30 * cm
# extra safety spacing before the Top-3 title (prevents collisions)
TOP3_TITLE_GAP = 0.45 * cm


def _clean_text(s: str) -> str:
    if not s:
        return s
    s = str(s).replace("\u00A0", " ")
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    s = s.replace("minutes'", "minutes").replace("minute'", "minute")
    s = s.replace("minute\u2019", "minute").replace("minutes\u2019", "minutes")
    return s

@lru_cache(maxsize=8)
def _microanchors_map_for_city(city: str) -> Dict[str, List[str]]:
    """
    Best-effort micro-anchors lookup from local city pack JSON.
    This keeps the PDF consistent even if LLM output omits micro_anchors.
    """
    try:
        if not city:
            return {}
        city_l = str(city).lower()
        # For now we only ship Brussels pack, keep it explicit & safe.
        if "brussels" not in city_l:
            return {}

        pack_path = Path(__file__).resolve().parents[1] / "city_packs" / "brussels.json"
        if not pack_path.exists():
            return {}

        data = json.loads(pack_path.read_text(encoding="utf-8"))

        out: Dict[str, List[str]] = {}

        def add_list(lst):
            if not isinstance(lst, list):
                return
            for it in lst:
                if not isinstance(it, dict):
                    continue
                nm = (it.get("name") or "").strip()
                if not nm:
                    continue
                micro = it.get("micro_anchors") or []
                if isinstance(micro, str):
                    micro = [micro]
                if isinstance(micro, list):
                    micro = [_clean_text(x) for x in micro if str(x).strip()]
                else:
                    micro = []
                if micro:
                    out[nm.lower()] = micro

        # Common layouts: top-level list, or nested lists under a dict
        for v in data.values():
            if isinstance(v, list):
                add_list(v)
            elif isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, list):
                        add_list(vv)

        return out
    except Exception:
        return {}


def _wrap(c: canvas.Canvas, text: str, max_width: float, font_name: str, font_size: float) -> List[str]:
    text = _clean_text(text or "")
    c.setFont(font_name, font_size)
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if c.stringWidth(test, font_name, font_size) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_section_title(c, x, y, title, accent):
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(accent)
    c.drawString(x, y, _clean_text(title))
    c.setFillColor(colors.black)


def _bullets_line_count(c: canvas.Canvas, items: List[str], max_width: float, font_size: float) -> int:
    c.setFont("Helvetica", font_size)
    total = 0
    for it in (items or []):
        lines = _wrap(c, f"• {it}", max_width, "Helvetica", font_size)
        total += max(1, len(lines))
    return total


def _draw_bullets(c, x, y, items: List[str], max_width, max_lines, font_size=9.0) -> Tuple[float, int]:
    c.setFont("Helvetica", font_size)
    line_h = font_size + 3
    used = 0
    for it in (items or [])[:max_lines]:
        it = _clean_text(str(it))
        lines = _wrap(c, f"• {it}", max_width, "Helvetica", font_size)
        for ln in lines:
            if used >= max_lines:
                return y - used * line_h, used
            c.drawString(x, y - used * line_h, ln)
            used += 1
    return y - used * line_h, used


def _mode_from_answers(answers: Dict[str, str]) -> str:
    if (answers.get("budget_rent") or "").strip():
        return "rent"
    if (answers.get("budget_buy") or "").strip():
        return "buy"
    ht = (answers.get("housing_type") or "").lower()
    if "rent" in ht:
        return "rent"
    return "buy"


def _fallback_questions(mode: str) -> List[str]:
    if mode == "rent":
        return [
            "What is the total move-in cost (deposit + first month + fees)?",
            "Which utilities are included, and typical monthly costs?",
            "Minimum lease term and early-termination policy?",
            "Any building rules in writing (noise, pets, renovations)?",
            "Is contract registration/indexation applicable and how?",
        ]
    return [
        "What are total purchase costs (taxes, notary, agency, other fees)?",
        "Is the property legally compliant (permits, energy cert, no liens)?",
        "Monthly charges (syndic/HOA) and what they cover?",
        "Any known defects / upcoming works / special assessments?",
        "Realistic closing timeline and negotiation flexibility?",
    ]


def _score_bar_no_label(c, x, y, value, width=44, height=6, accent=colors.HexColor("#2F66FF")):
    value = max(1, min(5, int(value or 3)))
    c.setFillColor(colors.HexColor("#E5E7EB"))
    c.roundRect(x, y, width, height, 3, fill=1, stroke=0)
    fill_w = width * (value / 5.0)
    c.setFillColor(accent)
    c.roundRect(x, y, fill_w, height, 3, fill=1, stroke=0)
    c.setFillColor(colors.black)


def _draw_card(c, x, y_top, w, h, bg, stroke, r=10):
    c.setFillColor(bg)
    c.roundRect(x, y_top - h, w, h, r, fill=1, stroke=0)
    c.setStrokeColor(stroke)
    c.roundRect(x, y_top - h, w, h, r, fill=0, stroke=1)


def _draw_link_list(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    max_width: float,
    label: str,
    items: List[Dict[str, Any]],
    label_color,
    link_color,
    font_size: float = 8.8,
    max_lines: int = 2
) -> float:
    label = _clean_text(label)
    c.setFont("Helvetica", font_size)
    line_h = font_size + 3

    c.setFillColor(label_color)
    c.drawString(x, y_top, label)
    label_w = c.stringWidth(label, "Helvetica", font_size)

    cur_x = x + label_w + 6
    cur_y = y_top
    used_lines = 1

    sep = " • "
    sep_w = c.stringWidth(sep, "Helvetica", font_size)

    for idx, it in enumerate(items or []):
        name = _clean_text((it.get("name") or "").strip()) or "—"
        url = (it.get("url") or "").strip()
        text_w = c.stringWidth(name, "Helvetica", font_size)

        if idx > 0:
            if cur_x + sep_w > x + max_width:
                used_lines += 1
                if used_lines > max_lines:
                    c.setFillColor(label_color)
                    c.drawString(x + max_width - c.stringWidth("…", "Helvetica", font_size), cur_y, "…")
                    return cur_y - (used_lines - 1) * line_h
                cur_y -= line_h
                cur_x = x
            c.setFillColor(label_color)
            c.drawString(cur_x, cur_y, sep)
            cur_x += sep_w

        if cur_x + text_w > x + max_width:
            used_lines += 1
            if used_lines > max_lines:
                c.setFillColor(label_color)
                c.drawString(x + max_width - c.stringWidth("…", "Helvetica", font_size), cur_y, "…")
                return cur_y - (used_lines - 1) * line_h
            cur_y -= line_h
            cur_x = x

        if url:
            c.setFillColor(link_color)
            c.drawString(cur_x, cur_y, name)
            c.linkURL(url, (cur_x, cur_y - 2, cur_x + text_w, cur_y + font_size + 1), relative=0)
        else:
            c.setFillColor(label_color)
            c.drawString(cur_x, cur_y, name)

        cur_x += text_w

    return cur_y - (used_lines - 1) * line_h


def render_minimal_premium_pdf(out_path: str, city: str, brief: Dict[str, Any], answers: Dict[str, str]) -> None:
    W, H = A4
    m = 1.6 * cm

    accent = colors.HexColor("#2F66FF")
    dark = colors.HexColor("#0B1220")
    muted = colors.HexColor("#6B7280")
    card_bg = colors.HexColor("#F9FAFB")
    stroke = colors.HexColor("#E5E7EB")
    link_blue = colors.HexColor("#2563EB")

    c = canvas.Canvas(out_path, pagesize=A4)

    # Header
    header_h = 2.8 * cm
    c.setFillColor(dark)
    c.rect(0, H - header_h, W, header_h, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(m, H - 1.25 * cm, _clean_text(f"Relocation Brief — {city}"))
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#C7D2FE"))
    c.drawString(m, H - 2.0 * cm, "Generated by Relocation Brief Builder")
    c.setFillColor(colors.HexColor("#E0E7FF"))
    c.drawRightString(W - m, H - 2.0 * cm, "1-page brief • shortlist • next steps")

    y = H - header_h - 0.5 * cm

    # Client profile
    prof_h = 2.55 * cm
    _draw_card(c, m, y, W - 2 * m, prof_h, card_bg, stroke)
    pad_x = 0.55 * cm
    top_pad = 0.52 * cm

    _draw_section_title(c, m + pad_x, y - top_pad, "Client profile", accent)

    c.setFillColor(muted)
    c.setFont("Helvetica", 8.2)
    mode_line = []
    if answers.get("budget_rent"):
        mode_line.append("Rent")
        mode_line.append(_clean_text(answers["budget_rent"]))
    if answers.get("budget_buy"):
        mode_line.append("Buy")
        mode_line.append(_clean_text(answers["budget_buy"]))
    ml = " • ".join([s for s in mode_line if s])
    if ml:
        c.drawString(m + pad_x, y - (top_pad + 0.48 * cm), ml)

    c.setFillColor(colors.black)
    font_prof = 9
    c.setFont("Helvetica", font_prof)
    line_h = 12  # points
    prof_text = _clean_text((brief.get("client_profile") or "").strip())
    max_w = W - 2 * m - 2 * pad_x
    lines = _wrap(c, prof_text, max_w, "Helvetica", font_prof)[:3]  # hard cap

    text_top_y = y - (top_pad + 0.92 * cm)
    yy = text_top_y
    for ln in lines:
        c.drawString(m + pad_x, yy, ln)
        yy -= line_h

    y = y - prof_h - GAP

    # Two columns
    col_gap = 0.6 * cm
    col_w = (W - 2 * m - col_gap) / 2
    left_x = m
    right_x = m + col_w + col_gap
    two_h = 5.6 * cm

    _draw_card(c, left_x, y, col_w, two_h, card_bg, stroke)
    _draw_section_title(c, left_x + 0.4 * cm, y - 0.55 * cm, "Must-have", accent)
    y1, _ = _draw_bullets(
        c, left_x + 0.4 * cm, y - 1.15 * cm,
        brief.get("must_have", []), col_w - 0.8 * cm, max_lines=4, font_size=8.8
    )
    _draw_section_title(c, left_x + 0.4 * cm, y1 - 0.45 * cm, "Nice-to-have", accent)
    _draw_bullets(
        c, left_x + 0.4 * cm, y1 - 1.05 * cm,
        brief.get("nice_to_have", []), col_w - 0.8 * cm, max_lines=4, font_size=8.8
    )

    _draw_card(c, right_x, y, col_w, two_h, card_bg, stroke)
    _draw_section_title(c, right_x + 0.4 * cm, y - 0.55 * cm, "Red flags", accent)
    y2, _ = _draw_bullets(
        c, right_x + 0.4 * cm, y - 1.15 * cm,
        brief.get("red_flags", []), col_w - 0.8 * cm, max_lines=4, font_size=8.8
    )
    _draw_section_title(c, right_x + 0.4 * cm, y2 - 0.45 * cm, "Trade-offs", accent)
    _draw_bullets(
        c, right_x + 0.4 * cm, y2 - 1.05 * cm,
        brief.get("contradictions", []), col_w - 0.8 * cm, max_lines=3, font_size=8.8
    )

    # IMPORTANT: extra spacing so Top-3 never collides with the two-column block
    y = y - two_h - GAP - TOP3_TITLE_GAP

    # Top-3 title
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.black)
    c.drawString(m, y, "Top-3 areas (shortlist)")
    y -= 0.45 * cm  # breathing room

    districts = (brief.get("top_districts") or [])[:3]

    top_font = 8.6
    step = 10.5

    # Increased a bit more: gives breathing room to Why/Watch-out text
    card_h = 3.55 * cm  # taller to fit micro-neighborhoods

    gap_h = GAP

    group_w = 3 * 44 + 2 * 10
    right_pad = 0.45 * cm
    gx = (W - m) - group_w - right_pad
    text_x = m + 0.4 * cm
    maxw = (gx - text_x) - 0.35 * cm

    for idx, d in enumerate(districts, 1):
        _draw_card(c, m, y, W - 2 * m, card_h, card_bg, stroke)

        base_name = _clean_text(d.get("name", "—"))
        micro = d.get("micro_anchors") or []
        if isinstance(micro, str):
            micro = [micro]
        if isinstance(micro, list):
            micro = [_clean_text(x) for x in micro if str(x).strip()]
        else:
            micro = []

        # If LLM didn't provide micro_anchors, pull them from the city pack (keeps output stable).
        if not micro:
            pack_map = _microanchors_map_for_city(city)
            micro = (pack_map.get(base_name.lower()) or [])[:3]

        name = base_name
        if micro:
            name = f"{base_name} ({', '.join(micro[:3])})"
        scores = d.get("scores", {}) or {}

        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(text_x, y - 0.50 * cm, f"{idx}) {name}")

        # bars
        gy = y - 0.78 * cm
        c.setFont("Helvetica", 7)
        c.setFillColor(muted)
        c.drawString(gx + 0,   gy + 10, "Safe")
        c.drawString(gx + 54,  gy + 10, "Fam")
        c.drawString(gx + 108, gy + 10, "Comm")
        c.setFillColor(colors.black)

        _score_bar_no_label(c, gx + 0,   gy, scores.get("Safety", 3), accent=accent)
        _score_bar_no_label(c, gx + 54,  gy, scores.get("Family", 3), accent=accent)
        _score_bar_no_label(c, gx + 108, gy, scores.get("Commute", 3), accent=accent)

        # row 2 (same style, directly under the first row)
        gy2 = gy - 0.72 * cm
        c.setFont("Helvetica", 7)
        c.setFillColor(muted)
        c.drawString(gx + 0,   gy2 + 10, "Life")
        c.drawString(gx + 54,  gy2 + 10, "Budget")
        c.setFillColor(colors.black)
        c.drawString(gx + 108, gy2 + 10, "Overall")
        c.setFillColor(colors.black)

        _score_bar_no_label(c, gx + 0,   gy2, scores.get("Lifestyle", 3), accent=accent)
        _score_bar_no_label(c, gx + 54,  gy2, scores.get("BudgetFit", 3), accent=accent)
        _score_bar_no_label(c, gx + 108, gy2, scores.get("Overall", 3), accent=colors.HexColor("#1B2ED6"))

        why_items = [_clean_text(x) for x in (d.get("why") or [])][:2]
        watch_item = (_clean_text((d.get("watch_out") or ["—"])[0]) if d.get("watch_out") else "—")

        # --- NEW: "Why: <text>" on the same line (no bullets) ---
        yy2 = y - 1.02 * cm  # slightly lower start for better top padding
        c.setFont("Helvetica", top_font)
        c.setFillColor(colors.black)

        why_text = "Why: " + " ".join([w.strip() for w in why_items if str(w).strip()])
        why_lines = _wrap(c, why_text, maxw, "Helvetica", top_font)[:3]  # allow up to 3 lines
        if not why_lines:
            why_lines = ["Why: —"]

        for ln in why_lines:
            c.drawString(text_x, yy2, ln)
            yy2 -= step

        # Watch-out (up to 2 lines)
        c.setFillColor(muted)
        watch_lines = _wrap(c, f"Watch-out: {watch_item}", maxw, "Helvetica", top_font)[:2]
        if not watch_lines:
            watch_lines = ["Watch-out: —"]

        c.drawString(text_x, yy2, watch_lines[0])
        if len(watch_lines) > 1:
            yy2 -= step
            c.drawString(text_x, yy2, watch_lines[1])
        y -= (card_h + gap_h)

        # Micro-neighborhoods (2-3) for this commune
        microhoods = d.get("microhoods") or []
        if isinstance(microhoods, list) and microhoods:
            yy2 -= step
            c.setFillColor(muted)
            mh_header = "Micro-neighborhoods:"
            c.drawString(text_x, yy2, mh_header)
            yy2 -= step

            c.setFillColor(text)
            for mh in microhoods[:3]:
                if not isinstance(mh, dict):
                    continue
                nm = str(mh.get("name","")).strip()
                why = str(mh.get("why","")).strip()
                wo = str(mh.get("watch_out","")).strip()

                line = f"• {nm}: {why}" if why else f"• {nm}"
                if wo:
                    line = f"{line} (Watch-out: {wo})"

                mh_lines = _wrap(c, line, maxw, "Helvetica", 7.6)[:2]
                for ln in mh_lines:
                    c.setFont("Helvetica", 7.6)
                    c.drawString(text_x, yy2, ln)
                    yy2 -= (7.6 + 2)

        y -= (card_h + gap_h)

    # Bottom blocks (same as your current version)
    bottom_min_y = 1.3 * cm

    next_items = [_clean_text(x) for x in (brief.get("next_steps") or [])]
    next_font = 8.6
    next_max_lines = 4
    next_line_h = next_font + 3
    next_needed_lines = min(_bullets_line_count(c, next_items[:next_max_lines], W - 2*m - 0.8*cm, next_font), next_max_lines)
    next_h = (0.66 * cm) + (next_needed_lines * next_line_h) + (0.46 * cm)

    res_h = 1.72 * cm

    mode = _mode_from_answers(answers)
    qs = [_clean_text(str(x)) for x in (brief.get("questions_for_agent_landlord") or []) if str(x).strip()]
    if len(qs) < 5:
        qs = _fallback_questions(mode)
    qs = qs[:5]

    q_font = 8.1
    q_max_lines = 7
    q_line_h = q_font + 3
    q_needed_lines = min(_bullets_line_count(c, qs, W - 2*m - 0.8*cm, q_font), q_max_lines)
    q_h = (0.66 * cm) + (q_needed_lines * q_line_h) + (0.48 * cm)

    total_bottom = next_h + GAP + res_h + GAP + q_h
    if y - total_bottom < bottom_min_y:
        next_font = 8.3
        q_font = 7.95
        next_max_lines = 3
        q_max_lines = 6

        next_line_h = next_font + 3
        next_needed_lines = min(_bullets_line_count(c, next_items[:next_max_lines], W - 2*m - 0.8*cm, next_font), next_max_lines)
        next_h = (0.62 * cm) + (next_needed_lines * next_line_h) + (0.42 * cm)

        q_line_h = q_font + 3
        q_needed_lines = min(_bullets_line_count(c, qs, W - 2*m - 0.8*cm, q_font), q_max_lines)
        q_h = (0.62 * cm) + (q_needed_lines * q_line_h) + (0.44 * cm)

    _draw_card(c, m, y, W - 2*m, next_h, card_bg, stroke)
    _draw_section_title(c, m + 0.4 * cm, y - 0.55 * cm, "Next steps", accent)
    _draw_bullets(c, m + 0.4 * cm, y - 1.0 * cm, next_items, W - 2*m - 0.8*cm,
                  max_lines=next_max_lines, font_size=next_font)
    y = y - next_h - GAP

    _draw_card(c, m, y, W - 2*m, res_h, card_bg, stroke)
    _draw_section_title(c, m + 0.4 * cm, y - 0.55 * cm, "Resources", accent)

    sites = (brief.get("real_estate_sites") or [])[:6]
    agencies = (brief.get("agencies") or [])[:6]

    y_links = y - 0.95 * cm
    maxw_links = W - 2*m - 0.8*cm

    _draw_link_list(
        c, m + 0.4*cm, y_links, maxw_links,
        "Websites:", sites,
        label_color=colors.black, link_color=link_blue,
        font_size=8.5, max_lines=2
    )
    _draw_link_list(
        c, m + 0.4*cm, y - 1.32 * cm, maxw_links,
        "Agencies:", agencies,
        label_color=colors.black, link_color=link_blue,
        font_size=8.5, max_lines=1
    )

    y = y - res_h - GAP

    _draw_card(c, m, y, W - 2*m, q_h, card_bg, stroke)
    _draw_section_title(c, m + 0.4 * cm, y - 0.55 * cm, "Essentials to ask your Real Estate agent", accent)
    _draw_bullets(c, m + 0.4 * cm, y - 1.0 * cm, qs, W - 2*m - 0.8*cm,
                  max_lines=q_max_lines, font_size=q_font)

    c.save()
