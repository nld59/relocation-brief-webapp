from __future__ import annotations

import json
import uuid
import time
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from brief_core.llm import draft_brief, finalize_brief
from brief_core.normalize import normalize_brief
from brief_core.render_md import render_md
from brief_core.render_pdf import render_minimal_premium_pdf

load_dotenv()

app = FastAPI(title="Relocation Brief API (v3)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUT_DIR = Path(__file__).resolve().parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)

STORE: Dict[str, Dict[str, Any]] = {}


@app.get("/health")
def health():
    return {"ok": True}


def _priorities_to_text(ids):
    mapping = {
        "green_parks": "Parks & green areas",
        "cafes_brunch": "Cafes & brunch",
        "restaurants": "Restaurants",
        "nightlife": "Nightlife",
        "culture_museums": "Culture & museums",
        "art_design": "Art & design",
        "shopping": "Shopping",
        "local_market_vibe": "Markets & local feel",
        "touristy": "Touristy / central buzz",
        "families": "Family-friendly",
        "expats_international": "Expats & international",
        "students": "Students",
        "young_professionals": "Young professionals",
        "older_quiet": "Quiet & calm",
        "residential_quiet": "Residential & quiet",
        "urban_dense": "Urban & dense",
        "houses_more": "More houses",
        "apartments_more": "More apartments",
        "premium_feel": "Premium feel",
        "value_for_money": "Value for money",
        "mixed_vibes": "Mixed vibe",
        "central_access": "Central access",
        "eu_quarter_access": "EU quarter access",
        "train_hubs_access": "Train hubs access",
        "airport_access": "Airport access",
        "metro_strong": "Strong metro",
        "tram_strong": "Strong tram",
        "bike_friendly": "Bike friendly",
        "car_friendly": "Car friendly",
        "night_caution": "Night caution",
        "busy_traffic_noise": "Traffic/noise",
        "schools_strong": "Schools access",
        "childcare_strong": "Childcare access",
        "parks": "Parks & green areas",
        "cafes": "Cafes & brunch",
        "safety": "Residential & quiet",
        "transit": "Strong metro",
        "family": "Family-friendly"
    }
    return ", ".join([mapping.get(x, x) for x in (ids or [])])



def _preview_lines(md: str, n: int = 10):
    lines = []
    for ln in md.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if len(ln) > 120:
            ln = ln[:117] + "..."
        lines.append(ln)
        if len(lines) >= n:
            break
    return lines


def ui_to_answers(payload: Dict[str, Any]) -> Dict[str, str]:
    city = (payload.get("city") or "").strip()

    household = payload.get("householdType") or ""
    children_count = int(payload.get("childrenCount") or 0)
    children_ages = payload.get("childrenAges") or []

    if household == "solo":
        family = "Solo"
    elif household == "couple":
        family = "Couple"
    elif household == "family":
        ages_txt = ", ".join([str(a).strip() for a in children_ages if str(a).strip()])
        family = (
            f"Family with {children_count} children (ages: {ages_txt})"
            if ages_txt
            else f"Family with {children_count} children"
        )
    else:
        family = ""

    mode = payload.get("mode") or "buy"
    bedrooms = payload.get("bedrooms") or ""
    prop_type = payload.get("propertyType") or ""
    bmin = payload.get("budgetMin")
    bmax = payload.get("budgetMax")

    if mode == "rent":
        budget_rent = f"{bmin}–{bmax} EUR/month" if bmin is not None and bmax is not None else ""
        budget_buy = ""
    else:
        budget_buy = f"{bmin}–{bmax} EUR purchase" if bmin is not None and bmax is not None else ""
        budget_rent = ""

    bed_txt = {"studio": "Studio", "1": "1+ room", "2": "2+ rooms", "3": "3+ rooms"}.get(
        str(bedrooms), str(bedrooms)
    )
    type_txt = {"apartment": "Apartment", "house": "House", "not_sure": "Not sure"}.get(
        str(prop_type), str(prop_type)
    )

    housing_type = f"{bed_txt}; type: {type_txt}; mode: {mode}"

    priorities = _priorities_to_text(payload.get("priorities") or [])

    raw_priority_ids = payload.get("priorities") or []
    if not isinstance(raw_priority_ids, list):
        raw_priority_ids = [str(raw_priority_ids)]
    # Map legacy 5-card ids to the 30-tag vocabulary ids
    legacy_map = {"parks": "green_parks", "cafes": "cafes_brunch", "safety": "residential_quiet", "transit": "metro_strong", "family": "families"}
    priority_ids = [legacy_map.get(x, x) for x in raw_priority_ids if str(x).strip()]
    # Keep selection order, cap to 7
    seen = set()
    priority_ids_ordered = []
    for x in priority_ids:
        if x in seen:
            continue
        seen.add(x)
        priority_ids_ordered.append(x)
        if len(priority_ids_ordered) >= 7:
            break
    top3_ids = priority_ids_ordered[:3]
    priority_tag_ids = ",".join(priority_ids_ordered)
    priority_top3_ids = ",".join(top3_ids)


    include_work = payload.get("includeWorkCommute")
    if include_work is True:
        work_transport = payload.get("workTransport") or ""
        work_minutes = payload.get("workMinutes") or ""
        work_address = (payload.get("workAddress") or "").strip()
        work_mode = "office/hybrid (commute preferences provided)" if work_address else "office/hybrid"
        office_location = work_address
        office_commute = f"{work_transport}, max {work_minutes} min"
    else:
        work_mode = "remote or not specified"
        office_location = ""
        office_commute = ""

    include_school = payload.get("includeSchoolCommute")
    if include_school is True:
        school_transport = payload.get("schoolTransport") or ""
        school_minutes = payload.get("schoolMinutes") or ""
        school_commute = f"{school_transport}, max {school_minutes} min"
        school_need = "Yes (commute preferences provided)"
    else:
        school_commute = ""
        school_need = ""

    lifestyle = f"Priorities: {priorities}" if priorities else ""

    return {
        "city": city,
        "family": family,
        "budget_rent": budget_rent,
        "budget_buy": budget_buy,
        "housing_type": housing_type,
        "lifestyle": lifestyle,
        "priorities": priorities,
        "priority_tag_ids": priority_tag_ids,
        "priority_top3_ids": priority_top3_ids,
        "school_need": school_need,
        "school_commute": school_commute,
        "work_mode": work_mode,
        "office_location": office_location,
        "office_commute": office_commute,
    }


def _render_all(
    brief_id: str,
    raw: Dict[str, Any],
    norm: Dict[str, Any],
    answers: Dict[str, str],
    *,
    render_files: bool,
):
    """Render MD/PDF to disk only when we are ready for download.

    We always return markdown content for UI preview, but we only write files
    (and compute pdf_ms) when `render_files=True`.
    """
    md = render_md(norm, city=answers.get("city") or "Relocation")

    # json (debug) is always saved, helpful for troubleshooting
    (OUT_DIR / f"{brief_id}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    pdf_ms = None
    if render_files:
        (OUT_DIR / f"{brief_id}.md").write_text(md, encoding="utf-8")

        pdf_path = OUT_DIR / f"{brief_id}.pdf"
        t0 = time.perf_counter()
        render_minimal_premium_pdf(
            out_path=str(pdf_path),
            city=answers.get("city") or "Relocation",
            brief=norm,
            answers=answers,
        )
        pdf_ms = int((time.perf_counter() - t0) * 1000)

    return md, pdf_ms


@app.post("/brief/draft")
def brief_draft(payload: Dict[str, Any]):
    total_t0 = time.perf_counter()

    answers = ui_to_answers(payload)
    if not answers.get("city"):
        raise HTTPException(status_code=400, detail="city is required")

    quality_mode = str(payload.get('qualityMode') or payload.get('quality_mode') or payload.get('quality') or 'fast').lower().strip()
    quality = quality_mode in ('quality','true','1','yes')

    llm_t0 = time.perf_counter()
    raw = draft_brief(answers, quality=quality)
    llm_ms = int((time.perf_counter() - llm_t0) * 1000)

    norm = normalize_brief(raw, city=answers.get("city"), answers=answers)

    brief_id = str(uuid.uuid4())[:8]
    STORE[brief_id] = {"answers": answers, "raw": raw, "norm": norm, "quality": quality}

    can_download = len(norm.get("clarifying_questions") or []) == 0
    md, pdf_ms = _render_all(brief_id, raw, norm, answers, render_files=can_download)

    total_ms = int((time.perf_counter() - total_t0) * 1000)

    return {
        "brief_id": brief_id,
        "clarifying_questions": norm.get("clarifying_questions", []),
        "preview_lines": _preview_lines(md, 10),
        "llm_ms": llm_ms,
        "pdf_render_ms": pdf_ms,
        "total_ms": total_ms,
        "can_download": can_download,
    }


@app.post("/brief/final")
def brief_final(payload: Dict[str, Any]):
    total_t0 = time.perf_counter()

    brief_id = payload.get("brief_id")
    clar = payload.get("clarifying_answers") or {}
    if not brief_id or brief_id not in STORE:
        raise HTTPException(status_code=404, detail="brief_id not found")

    saved = STORE[brief_id]
    answers = saved["answers"]
    current_raw = saved["raw"]

    llm_t0 = time.perf_counter()
    updated_raw = finalize_brief(answers, current_raw, clar)
    llm_ms = int((time.perf_counter() - llm_t0) * 1000)

    updated = normalize_brief(updated_raw, city=answers.get("city"), answers=answers)
    STORE[brief_id] = {"answers": answers, "raw": updated_raw, "norm": updated, "quality": saved.get("quality", False)}

    can_download = len(updated.get("clarifying_questions") or []) == 0
    md, pdf_ms = _render_all(brief_id, updated_raw, updated, answers, render_files=can_download)

    total_ms = int((time.perf_counter() - total_t0) * 1000)

    return {
        "brief_id": brief_id,
        "clarifying_questions": updated.get("clarifying_questions", []),
        "preview_lines": _preview_lines(md, 10),
        "llm_ms": llm_ms,
        "pdf_render_ms": pdf_ms,
        "total_ms": total_ms,
        "can_download": can_download,
    }


@app.get("/brief/download")
def brief_download(brief_id: str, format: str = "pdf"):
    if not brief_id:
        raise HTTPException(status_code=400, detail="brief_id is required")
    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "md"):
        raise HTTPException(status_code=400, detail="format must be pdf or md")

    path = OUT_DIR / f"{brief_id}.{fmt}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")

    media = "application/pdf" if fmt == "pdf" else "text/markdown"
    filename = f"relocation-brief-{brief_id}.{fmt}"
    return FileResponse(str(path), media_type=media, filename=filename)