from __future__ import annotations

"""Normalize and enrich the LLM brief.

Goals:
1) Keep output deterministic and safe for rendering (PDF/MD).
2) Enforce *area selection* from city packs only.
3) Ensure microhoods exist (2–3 per top commune) and come from city packs.
4) Avoid placeholder rows like "—" unless data is truly missing.
5) Make the brief multi-page friendly (no aggressive truncation).
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .city_packs import load_city_pack
from .quality_gate import run_quality_gate

# --- Scoring model (used for Trust & method copy + debug output) ---
SCORE_MODEL: Dict[str, Any] = {
    "dimensions": {
        "Safety": {
            "signals": ["safety_index (city-pack)", "quiet/residential tags", "nightlife/traffic penalties"],
        },
        "Family": {
            "signals": ["family_index (city-pack)", "parks/schools/childcare tags", "household with kids boost"],
        },
        "Commute": {
            "signals": ["commute_index (city-pack)", "metro/tram/train tags", "traffic penalty when not car-friendly"],
        },
        "Lifestyle": {
            "signals": ["lifestyle_index (city-pack)", "cafes/restaurants/culture tags"],
        },
        "BudgetFit": {
            "signals": [
                "your stated rent/buy budget",
                "premium/central preference tags",
                "commune cost-pressure proxy (lifestyle + 0.8*commute percentile)",
            ],
        },
    },
    "overall": "Overall = round( (Safety + Family + Commute + Lifestyle + BudgetFit) / 5 )",
    "scale": {
        "5": "consistently strong across most pockets",
        "3": "mixed; street-by-street variation",
        "2": "often requires trade-offs",
    },
}


# High-level caps (multi-page report, so keep them generous)
LIMITS = {
    "client_profile_chars": 520,
    "must_have": 8,
    "nice_to_have": 8,
    "red_flags": 8,
    "contradictions": 8,
    "questions": 7,
    "clarifying_questions": 5,
    "next_steps": 12,
    "district_why": 4,
    "district_watch": 2,
    "microhoods": 3,
}


# --- Premium report normalization helpers ---

def _normalize_dashes(s: str) -> str:
    """Normalize spacing around hyphens: 'Saint - Job' -> 'Saint-Job'."""
    if not s:
        return ""
    # collapse whitespace around hyphen
    s = re.sub(r"\s*-\s*", "-", s)
    # collapse multiple spaces
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _dedupe_str_list(items):
    """Case-insensitive stable dedupe + trim; drops empties."""
    out = []
    seen = set()
    for it in items or []:
        s = (it or "").strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(_normalize_dashes(s))
    return out



def _clean_text(s: object) -> str:
    """Basic sanitizer for free-form text fields.

    Goals:
    - Remove invisible Unicode joiners / no-break spaces that some PDF fonts/viewers
      show as black squares.
    - Normalize hyphen variants to plain ASCII '-'.
    - Collapse multiple spaces.
    """
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)

    # Normalize whitespace / joiners
    for ch in (" ", " ", " "):
        s = s.replace(ch, " ")
    for ch in ("⁠", "​", "﻿"):
        s = s.replace(ch, "")

    # Normalize punctuation / hyphens
    s = (s
         .replace("’", "'")
         .replace("“", '"')
         .replace("”", '"')
         .replace("‑", "-")  # non-breaking hyphen
         .replace("‐", "-")  # hyphen
         .replace("–", "-")  # en dash
         .replace("—", "-")  # em dash
         .replace("■", "-")
         .replace("□", "-")
         .replace("▪", "-")
         .replace("▫", "-")
    )

    s = _normalize_dashes(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_bullets(items):
    """Remove empty bullets + normalize dashes + dedupe."""
    return _dedupe_str_list(items)


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def _recalc_overall(scores: dict) -> int:
    """Overall = rounded average of 5 dimensions. Returned as 1..5 int."""
    keys = ["Safety", "Family", "Commute", "Lifestyle", "BudgetFit"]
    vals = []
    for k in keys:
        if k in scores:
            vals.append(_safe_int(scores.get(k), 0))
    if not vals:
        return _safe_int(scores.get("Overall"), 0)
    avg = sum(vals) / len(vals)
    # round halves up
    overall = int(avg + 0.5)
    return max(1, min(5, overall))


def _postprocess_brief(out: dict) -> dict:
    """Final consistency pass for premium PDF rendering."""
    # Normalize / dedupe top-level bullets
    for k in ["must_have", "nice_to_have", "red_flags", "contradictions"]:
        if k in out:
            out[k] = _clean_bullets(out.get(k, []))

    # Normalize dashes in key strings
    for k in ["city", "country", "report_title", "client_profile"]:
        if k in out and isinstance(out[k], str):
            out[k] = _normalize_dashes(out[k])

    # Normalize / enrich commune blocks
    districts = out.get("top_districts") or []
    for d in districts:
        d["commune"] = _normalize_dashes(d.get("commune", ""))
        # score keys may vary
        scores = d.get("scores") or {}
        # normalize score keys casing
        norm_scores = {}
        for kk, vv in list(scores.items()):
            if not kk:
                continue
            key = kk.strip()
            # common variants
            key_map = {
                "budget_fit": "BudgetFit",
                "budgetfit": "BudgetFit",
                "overall": "Overall",
                "safety": "Safety",
                "family": "Family",
                "commute": "Commute",
                "lifestyle": "Lifestyle",
            }
            k2 = key_map.get(key.casefold(), key)
            norm_scores[k2] = vv
        # ensure ints
        for k2 in ["Safety", "Family", "Commute", "Lifestyle", "BudgetFit", "Overall"]:
            if k2 in norm_scores:
                norm_scores[k2] = _safe_int(norm_scores.get(k2), 0)
        norm_scores["Overall"] = _recalc_overall(norm_scores)
        d["scores"] = norm_scores

        # microhoods schema normalization
        # Sprint-2+ update: remove generic Street hints / Avoid blocks (they were identical
        # everywhere and not valuable). Keep portal keywords + a microhood-specific
        # 2-3 sentence "highlights" blurb.
        mh_out = []
        for mh in d.get("microhoods", []) or []:
            name = _normalize_dashes((mh.get("name") or "").strip())
            if not name:
                continue
            portal_keywords = _dedupe_str_list(mh.get("portal_keywords") or mh.get("keywords") or [])
            highlights = _normalize_dashes((mh.get("highlights") or mh.get("why") or "").strip())

            if not portal_keywords:
                # build minimal useful keywords
                base = [name, "Brussels"]
                portal_keywords = _dedupe_str_list(base)
            portal_keywords = portal_keywords[:4]

            if not highlights:
                # Fallback to a short, non-generic sentence. (Prefer deterministic profile-based
                # highlights populated later in the pipeline.)
                highlights = "Good starting point with balanced everyday amenities."

            mh_out.append({
                "name": name,
                "portal_keywords": portal_keywords,
                "highlights": highlights,
            })
        d["microhoods"] = mh_out

        # normalize budget reality text
        if "budget_reality" in d:
            br = d.get("budget_reality")
            if isinstance(br, str):
                d["budget_reality"] = _normalize_dashes(br)
            elif isinstance(br, list):
                d["budget_reality"] = [_normalize_dashes(x) for x in br if (x or "").strip()]

    # Sort top districts by Overall desc, then Family desc, then Safety desc
    def _sort_key(d):
        s = (d.get("scores") or {})
        return (
            _safe_int(s.get("Overall"), 0),
            _safe_int(s.get("Family"), 0),
            _safe_int(s.get("Safety"), 0),
        )

    out["top_districts"] = sorted(districts, key=_sort_key, reverse=True)
    return out


def _parse_money(value: Any) -> Optional[int]:
    """Parse a money-ish string to an integer amount.

    Accepts values like "2500", "€2,500", "2 500 EUR", "1.2M".
    Returns None when parsing fails.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return None

    # Handle suffixes like 1.2M / 750k
    m = re.match(r"^\s*([0-9]+(?:[\.,][0-9]+)?)\s*([kKmM])\s*$", s)
    if m:
        num = float(m.group(1).replace(",", "."))
        suf = m.group(2).lower()
        return int(num * (1_000 if suf == "k" else 1_000_000))

    # Strip currency symbols and keep digits.
    # NOTE: ranges like "745000-1205000" are NOT supported here because this
    # would concatenate the digits. Use _parse_money_range() for ranges.
    digits = re.sub(r"[^0-9]", "", s)
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _parse_money_range(value: Any) -> Tuple[Optional[int], Optional[int]]:
    """Parse a money value that may represent a range.

    Supported examples:
    - "745000-1205000" / "745000 – 1205000"
    - "€745k–€1.2M"
    - single numbers (returns (n, n))
    """
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        n = int(value)
        return n, n

    s = str(value).strip()
    if not s:
        return None, None

    # Normalize dash variants
    s_norm = re.sub(r"[–—]", "-", s)
    # Split on a dash that is likely a range separator
    if "-" in s_norm:
        parts = [p.strip() for p in s_norm.split("-") if p.strip()]
        if len(parts) >= 2:
            a = _parse_money(parts[0])
            b = _parse_money(parts[1])
            if a and b:
                lo, hi = (a, b) if a <= b else (b, a)
                return lo, hi

    n = _parse_money(s_norm)
    if n is None:
        return None, None
    return n, n


def _clamp_1_5(v: float) -> int:
    return max(1, min(5, int(round(v))))


def _clamp_2_5(v: float) -> int:
    """Keep ratings realistic (avoid 1/5 unless explicitly needed)."""
    return max(2, min(5, int(round(v))))


def _percentile_rank(values: List[float], v: float) -> float:
    """Deterministic percentile rank in [0, 1].

    We intentionally use a simple inclusive rank to make the output stable
    across runs. This helps avoid the "everything is 5/5" trust issue by
    spreading communes relative to each other.
    """
    if not values:
        return 0.5
    vals = sorted(float(x) for x in values)

    # Mid-rank percentile (reduces tie inflation to 1.0).
    lt = 0
    eq = 0
    for x in vals:
        if x < v:
            lt += 1
        elif x == v:
            eq += 1
        else:
            break

    n = float(len(vals))
    if n <= 0:
        return 0.5

    p = (lt + 0.5 * eq) / n
    return max(0.0, min(1.0, p))


def _norm_minmax(value: float, mn: float, mx: float) -> float:
    if mx <= mn:
        return 0.5
    return (value - mn) / (mx - mn)


def _load_microhood_commune_map() -> Dict[str, str]:
    """Map microhood name variants -> commune_en using monitoring_quartiers_full.geojson.

    This is used as a validator so we never recommend microhoods outside the selected commune.
    """
    geo_path = Path(__file__).resolve().parent.parent / "city_packs" / "monitoring_quartiers_full.geojson"
    if not geo_path.exists():
        return {}
    try:
        data = json.loads(geo_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    out: Dict[str, str] = {}
    for feat in data.get("features", []) or []:
        props = feat.get("properties") or {}
        commune = _as_str(props.get("commune_en"))
        if not commune:
            continue
        for k in ["name_fr", "name_nl", "name_bil"]:
            nm = _as_str(props.get(k))
            if not nm:
                continue
            out[_norm_label(nm)] = commune
    return out


def _as_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i).strip() for i in x if str(i).strip()]
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return []
        parts = [p.strip("-• \t") for p in re.split(r"[\n,;]+", s) if p.strip()]
        return parts if parts else [s]
    return [str(x).strip()]


def _as_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict):
        return json.dumps(x, ensure_ascii=False)
    return str(x).strip()


def _trim(lst: List[str], n: int) -> List[str]:
    return lst[:n] if n and n > 0 else lst


def _score_obj(x: Any) -> Dict[str, int]:
    keys = ["Safety", "Family", "Commute", "Lifestyle", "BudgetFit", "Overall"]
    s: Dict[str, int] = {}
    if isinstance(x, dict):
        for k in keys:
            v = x.get(k) if k in x else x.get(k.lower())
            if v is None:
                continue
            try:
                s[k] = max(1, min(5, int(v)))
            except Exception:
                pass
    # defaults
    for k in ["Safety", "Family", "Commute", "Lifestyle", "BudgetFit"]:
        s.setdefault(k, 3)
    if "Overall" not in s:
        base = [s[k] for k in ["Safety", "Family", "Commute", "Lifestyle", "BudgetFit"]]
        s["Overall"] = int(round(sum(base) / len(base)))
    return s


def _norm_links(items: Any) -> List[Dict[str, str]]:
    if items is None:
        return []
    if isinstance(items, dict):
        items = [items]
    if isinstance(items, str):
        items = _as_list(items)
    out: List[Dict[str, str]] = []
    for it in items:
        if isinstance(it, str):
            out.append({"name": it.strip() or "—", "url": "", "note": ""})
        elif isinstance(it, dict):
            out.append(
                {
                    "name": _as_str(it.get("name", "—")) or "—",
                    "url": _as_str(it.get("url", "")),
                    "note": _as_str(it.get("note", "")),
                }
            )
        else:
            out.append({"name": _as_str(it) or "—", "url": "", "note": ""})
    return out


def _norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _split_csv(value: str) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _priority_match(
    commune_tags: List[str],
    priority_ids: List[str],
    top3_ids: List[str],
) -> Dict[str, List[str]]:
    strong = [t for t in commune_tags if t in top3_ids]
    medium = [t for t in commune_tags if (t in priority_ids and t not in strong)]
    return {"strong": strong[:3], "medium": medium[:4]}


def _priority_snapshot(tags: List[str], scores: Dict[str, int], metrics: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    # Cost / budget feel
    bf = int(scores.get("BudgetFit", 3))
    if "premium_feel" in tags or bf <= 2:
        cost = "Higher cost; budget may feel tight in prime streets."
    elif "value_for_money" in tags or bf >= 4:
        cost = "Better value vs central premium areas; more space for the budget."
    else:
        cost = "Mid-range pricing; specific streets vary a lot."

    # Transit
    # Transit: prefer metrics if available to avoid tag-only hallucinations
    metro_d = float((metrics or {}).get("metro_density") or 0)
    tram_d = float((metrics or {}).get("tram_density") or 0)
    train_d = float((metrics or {}).get("train_density") or 0)
    transit_bits = []
    if metro_d >= 0.6 or "metro_strong" in tags:
        transit_bits.append("metro access")
    if tram_d >= 2.5 or "tram_strong" in tags:
        transit_bits.append("tram coverage")
    if train_d >= 0.2 or "train_hubs_access" in tags:
        transit_bits.append("near train links")
    transit = ", ".join(transit_bits) if transit_bits else "bus-based; verify nearest stops"

    # Commute / access
    access_bits = []
    if "central_access" in tags:
        access_bits.append("city center")
    if "eu_quarter_access" in tags:
        access_bits.append("EU quarter")
    if "airport_access" in tags:
        access_bits.append("airport")
    commute_access = ", ".join(access_bits) if access_bits else "depends on address; check travel times"

    # Family
    parks_share = float((metrics or {}).get("parks_share") or 0)
    if any(t in tags for t in ["families", "schools_strong", "childcare_strong", "green_parks"]) or parks_share >= 0.12:
        schools_family = "generally family-friendly; parks/schools are a key advantage"
    else:
        schools_family = "varies by pocket; check schools/childcare options nearby"

    return {
        "housing_cost": cost,
        "transit": transit,
        "commute_access": commute_access,
        "schools_family": schools_family,
    }


def _microhood_sentence_from_metrics(mh: Dict[str, Any]) -> Tuple[str, str]:
    """Generate a short why/watch_out if not provided."""
    metrics = mh.get("metrics") or {}
    tc = mh.get("tag_confidence") or {}
    parks_share = float(metrics.get("parks_share") or 0)
    cafes_d = float(metrics.get("cafes_density") or 0)
    tram_d = float(metrics.get("tram_stop_density") or 0)
    metro_d = float(metrics.get("metro_station_density") or 0)

    why_bits = []
    if parks_share >= 0.15 or tc.get("green_parks"):
        why_bits.append("more green space")
    if cafes_d >= 10:
        why_bits.append("active cafe scene")
    if metro_d >= 0.8:
        why_bits.append("good metro access")
    elif tram_d >= 2.0:
        why_bits.append("good tram coverage")
    if not why_bits:
        why_bits.append("balanced everyday amenities")
    why = f"Good starting point with {', '.join(why_bits)}.".strip()

    watch_bits = []
    if cafes_d >= 12:
        watch_bits.append("busier evenings")
    if parks_share < 0.05:
        watch_bits.append("less greenery")
    if not watch_bits:
        watch_bits.append("street-to-street variation")
    watch = f"Watch for {', '.join(watch_bits)}.".strip()

    return why, watch


def _derive_strengths_tradeoffs(
    tags: List[str],
    snapshot: Dict[str, str],
    *,
    anchors: List[str],
    scores: Optional[Dict[str, int]] = None,
    tenure: str = "buy",
) -> Tuple[List[str], List[str]]:
    """Generate market-sounding strengths/trade-offs from deterministic inputs."""

    anchors = [a for a in (anchors or []) if a]
    anchor_hint = anchors[0] if anchors else "key local hubs"

    strengths: List[str] = []
    tradeoffs: List[str] = []

    scores = scores or {}

    # Strengths (tag-driven)
    if "expats_international" in tags:
        strengths.append("Strong international / expat ecosystem and services.")
    if "eu_quarter_access" in tags:
        strengths.append("Very convenient access to the EU Quarter and central corridors.")
    if "green_parks" in tags or "families" in tags or "residential_quiet" in tags:
        if "green_parks" in tags:
            strengths.append(f"Stronger green pockets around {anchor_hint} (parks and calmer streets).")
        else:
            strengths.append(f"Calmer, more residential pockets around {anchor_hint} compared with busier hubs.")
    if "cafes_brunch" in tags or "restaurants" in tags:
        strengths.append("Plenty of day-to-day amenities (cafés, restaurants) within walking distance.")
    if "metro_strong" in tags or "tram_strong" in tags:
        strengths.append("Reliable public transport coverage for everyday commuting.")

    # Score-derived (commune-specific, helps avoid copy/paste text)
    if int(scores.get("Commute", 3)) >= 4:
        strengths.append("Above-average connectivity for commuting across Brussels.")
    if int(scores.get("Lifestyle", 3)) >= 4:
        strengths.append("Stronger lifestyle density (cafés/amenities) compared with quieter communes.")
    if int(scores.get("Family", 3)) >= 4:
        strengths.append("Often preferred by families due to parks/schools access and calmer pockets.")

    # If the first bullet is still generic across communes, promote the strongest driver.
    # This makes the report feel less templated and improves "scan in 60s".
    driver_candidates: List[str] = []
    if int(scores.get("Family", 3)) >= 4:
        driver_candidates.append(f"Family-oriented pockets around {anchor_hint} with parks/schools within reach.")
    if int(scores.get("Commute", 3)) >= 4:
        driver_candidates.append(f"Above-average commute convenience around {anchor_hint} via metro/tram corridors.")
    if int(scores.get("Lifestyle", 3)) >= 4:
        driver_candidates.append(f"Higher amenity density near {anchor_hint} (cafés, restaurants) for day-to-day life.")
    if driver_candidates:
        first = strengths[0] if strengths else ""
        if first.lower().startswith("good balance") or first.lower().startswith("stronger green") or first.lower().startswith("calmer"):
            # Insert after the first line to keep the tone natural.
            strengths = strengths[:1] + [driver_candidates[0]] + strengths[1:]

    # Snapshot-derived (keeps it grounded)
    if snapshot.get("commute_access"):
        strengths.append(f"Good access to {snapshot['commute_access']} from {anchor_hint}.")

    # Trade-offs
    if "busy_traffic_noise" in tags:
        tradeoffs.append("Traffic/noise can be noticeable on main arteries; shortlist street-by-street.")
    if "nightlife" in tags or "night_caution" in tags:
        tradeoffs.append("Busier evenings in hotspots; confirm noise levels during a late walk-through.")
    if "premium_feel" in tags or int(scores.get("BudgetFit", 3)) <= 2:
        if tenure == "rent":
            tradeoffs.append("Prime pockets can be pricey; validate the full monthly cost (rent + charges + utilities).")
        else:
            tradeoffs.append("Prime pockets can be pricey; validate the full purchase cost (price + fees + recurring charges).")
    if "car_friendly" not in tags and "parking_tight" in tags:
        tradeoffs.append("Parking can be challenging without a private spot; verify permits early.")
    if snapshot.get("housing_cost"):
        tradeoffs.append(snapshot["housing_cost"].replace("Typical housing cost", ""))

    # De-duplicate while preserving order
    def _dedupe(items: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in items:
            key = _norm_label(x)
            if key in seen:
                continue
            seen.add(key)
            out.append(x)
        return out

    strengths = _dedupe([s for s in strengths if s])[:4]
    tradeoffs = _dedupe([t for t in tradeoffs if t])[:3]
    if not strengths:
        strengths = [f"Strong fit for your priorities around {anchor_hint}.", "Balanced lifestyle and commute trade-off."]
    if not tradeoffs:
        tradeoffs = ["Verify street-level noise/parking and building condition during viewings."]

    return strengths, tradeoffs


def _uniqueize_shortlist_copy(
    districts: List[Dict[str, Any]],
    *,
    answers: Optional[Dict[str, Any]] = None,
) -> None:
    """Reduce copy/paste feel across the 3-commune shortlist.

    We keep the content deterministic (no LLM calls) but ensure:
    - strengths/tradeoffs are not identical across communes
    - first strength is a clear, commune-specific driver (family/commute/lifestyle/budget)
    """
    answers = answers or {}

    # Rank districts by key dimensions so we can write "best for X" lines without inventing facts.
    dims = ["Family", "Commute", "Lifestyle", "BudgetFit", "Safety"]
    scores_by_dim: Dict[str, List[int]] = {d: [] for d in dims}
    for d in districts:
        sc = d.get("scores") or {}
        for dim in dims:
            try:
                scores_by_dim[dim].append(int(sc.get(dim, 0)))
            except Exception:
                scores_by_dim[dim].append(0)

    # Helper: rank index (0 = best)
    def _rank_indices(vals: List[int]) -> List[int]:
        # Higher is better. Stable tie-break by original order.
        order = sorted(range(len(vals)), key=lambda i: (-vals[i], i))
        rank = [0] * len(vals)
        for r, i in enumerate(order):
            rank[i] = r
        return rank

    ranks = {dim: _rank_indices(scores_by_dim[dim]) for dim in dims}

    commute_to = _as_str(
        answers.get("commute_to") or answers.get("commute_destination") or answers.get("work_location") or ""
    ).strip()
    commute_to = commute_to[:60]

    used_strength_keys: set[str] = set()
    used_tradeoff_keys: set[str] = set()

    for i, d in enumerate(districts):
        anchors = d.get("micro_anchors") or d.get("anchors") or []
        anchor_hint = anchors[0] if anchors else d.get("name") or "key hubs"
        sc = d.get("scores") or {}

        # Candidate first-strength lines (ordered by what usually sells best for families).
        cand: List[str] = []
        if ranks.get("Family", [99])[i] == 0 and int(sc.get("Family", 0)) >= 4:
            cand.append(f"Best family fit in the shortlist: calmer pockets near {anchor_hint} and good parks/schools access.")
        if ranks.get("Commute", [99])[i] == 0 and int(sc.get("Commute", 0)) >= 4:
            if commute_to:
                cand.append(f"Strongest commute option: often the easiest access to {commute_to} from around {anchor_hint}.")
            else:
                cand.append(f"Strongest commute option: above-average connectivity around {anchor_hint} via metro/tram corridors.")
        if ranks.get("Lifestyle", [99])[i] == 0 and int(sc.get("Lifestyle", 0)) >= 4:
            cand.append(f"Most lifestyle-dense option: cafés/amenities cluster more strongly around {anchor_hint}.")
        if ranks.get("BudgetFit", [99])[i] == 0 and int(sc.get("BudgetFit", 0)) >= 4:
            cand.append(f"Best value fit: more options within budget compared with the other shortlisted communes.")
        if not cand:
            # Fallback that still reads specific
            cand.append(f"Balanced option around {anchor_hint} with a clear trade-off between space, commute and amenities.")

        strengths = [s for s in (d.get("strengths") or []) if isinstance(s, str) and s.strip()]
        tradeoffs = [t for t in (d.get("tradeoffs") or []) if isinstance(t, str) and t.strip()]

        # Replace generic repeated starters.
        if strengths:
            first_key = _norm_label(strengths[0])
            if first_key in used_strength_keys or strengths[0].lower().startswith("plenty of day-to-day") or strengths[0].lower().startswith("good access to"):
                strengths[0] = cand[0]
        else:
            strengths = [cand[0]]

        # De-dupe across districts by replacing duplicates with specific alternatives.
        def _push_unique(items: List[str], used: set[str], alts: List[str]) -> List[str]:
            out: List[str] = []
            for x in items:
                k = _norm_label(x)
                if k in used:
                    continue
                used.add(k)
                out.append(x)
            # Fill up to original length (max 4/3) with alternatives that are not yet used.
            for a in alts:
                if len(out) >= len(items):
                    break
                k = _norm_label(a)
                if k in used:
                    continue
                used.add(k)
                out.append(a)
            return out

        # Strength alternatives to reduce templating feel
        alt_strengths: List[str] = []
        if int(sc.get("Safety", 0)) >= 4:
            alt_strengths.append("Generally calmer residential feel compared with central nightlife hubs.")
        if int(sc.get("BudgetFit", 0)) <= 2:
            alt_strengths.append("Prime pockets can be competitive; widen the search radius within the commune to keep options.")

        strengths = _push_unique(strengths, used_strength_keys, alt_strengths)[:4]

        # Trade-off alternatives
        alt_trade: List[str] = []
        if int(sc.get("BudgetFit", 0)) <= 2:
            alt_trade.append("Competition can be high in prime pockets; be ready to move quickly on good listings.")
        if int(sc.get("Commute", 0)) <= 2:
            alt_trade.append("Commute convenience varies; test your door-to-door route at peak hours before committing.")
        alt_trade.append("Check building charges (syndic), EPC, and noise insulation — these vary street-by-street.")

        tradeoffs = _push_unique(tradeoffs, used_tradeoff_keys, alt_trade)[:3]

        d["strengths"] = strengths
        d["tradeoffs"] = tradeoffs





def _build_commune_score_index(pack: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, float]], Dict[str, List[float]]]:
    """Precompute raw feature scores and distributions for scaling across communes.

    We keep the scoring deterministic and *relative* (percentile-based) so
    communes don't all collapse to the same 5/5 ratings.
    """
    communes = pack.get("communes") or []
    rows = []
    for c in communes:
        m = c.get("metrics") or {}
        tags = c.get("tags") or []
        lifestyle = float(m.get("cafes_density") or 0) + 0.6 * float(m.get("restaurants_density") or 0) + 0.8 * float(m.get("bars_density") or 0)
        commute = 3.0 * float(m.get("metro_density") or 0) + 1.0 * float(m.get("tram_density") or 0) + 2.0 * float(m.get("train_density") or 0)
        family = 1.2 * float(m.get("schools_density") or 0) + 2.0 * float(m.get("childcare_density") or 0) + 18.0 * float(m.get("parks_share") or 0)
        safety = 4.0
        if "night_caution" in tags:
            safety -= 0.7
        if "nightlife" in tags:
            safety -= 0.3
        if "older_quiet" in tags or "residential_quiet" in tags:
            safety += 0.4
        if "busy_traffic_noise" in tags:
            safety -= 0.2
        rows.append((c.get("name"), {"lifestyle": lifestyle, "commute": commute, "family": family, "safety": safety}))

    dists = {
        "lifestyle": [r[1]["lifestyle"] for r in rows if r[0]],
        "commute": [r[1]["commute"] for r in rows if r[0]],
        "family": [r[1]["family"] for r in rows if r[0]],
        "safety": [r[1]["safety"] for r in rows if r[0]],
    }

    idx: Dict[str, Dict[str, float]] = {}
    for name, raw in rows:
        if not name:
            continue
        idx[name] = {
            "lifestyle": float(raw["lifestyle"]),
            "commute": float(raw["commute"]),
            "family": float(raw["family"]),
            "safety": float(raw["safety"]),
        }
    return idx, dists


def _compute_budget_fit(
    tags: List[str],
    *,
    answers: Optional[Dict[str, Any]] = None,
    commune: Optional[Dict[str, Any]] = None,
    score_index: Optional[Dict[str, Dict[str, float]]] = None,
    score_dists: Optional[Dict[str, List[float]]] = None,
    return_debug: bool = False,
) -> Any:
    """Budget fit heuristic (2-5) based on budget *and* commune cost pressure.

    We do not have official pricing data in the pack. To avoid misleading
    precision we approximate "cost pressure" from amenity + connectivity
    densities (lifestyle + commute). This creates realistic variation between
    communes and prevents identical BudgetFit everywhere.
    """
    answers = answers or {}
    rent_lo, rent_hi = _parse_money_range(answers.get("budget_rent"))
    buy_lo, buy_hi = _parse_money_range(answers.get("budget_buy"))

    # Use the *upper* end as what the client can realistically spend.
    rent = rent_hi
    buy = buy_hi

    if not rent and not buy:
        return (3, {"reason": "no_budget"}) if return_debug else 3

    premium = "premium_feel" in tags
    central = "central_access" in tags

    # Commune cost pressure (percentile of lifestyle+commute raw index)
    pressure_p = 0.5
    if commune and score_index and score_dists:
        name = commune.get("name")
        base = score_index.get(name or "", {})
        pressure_raw = float(base.get("lifestyle", 0.0)) + 0.8 * float(base.get("commute", 0.0))
        dist = [float(r.get("lifestyle", 0.0)) + 0.8 * float(r.get("commute", 0.0)) for r in score_index.values()]
        pressure_p = _percentile_rank(dist, pressure_raw)

    # Convert pressure percentile to an integer penalty (0..2)
    pressure_pen = 2 if pressure_p >= 0.8 else (1 if pressure_p >= 0.55 else 0)

    debug = {
        "rent_hi": rent_hi,
        "buy_hi": buy_hi,
        "premium": bool(premium),
        "central": bool(central),
        "pressure_percentile": pressure_p,
        "pressure_penalty": pressure_pen,
    }

    # Very rough tiers (Brussels): rent in EUR/mo, buy in EUR
    if rent and not buy:
        # Baseline per preference
        if premium or central:
            base = 4 if rent >= 2800 else (3 if rent >= 2200 else 2)
        else:
            base = 4 if rent >= 2000 else (3 if rent >= 1500 else 2)
        score = max(2, min(5, base - pressure_pen))
        if return_debug:
            debug.update({"mode": "rent", "base": base, "final": score})
            return score, debug
        return score

    if buy:
        if premium or central:
            base = 4 if buy >= 850_000 else (3 if buy >= 650_000 else 2)
        else:
            base = 4 if buy >= 650_000 else (3 if buy >= 450_000 else 2)
        score = max(2, min(5, base - pressure_pen))
        if return_debug:
            debug.update({"mode": "buy", "base": base, "final": score})
            return score, debug
        return score

    return (3, {"reason": "fallback"}) if return_debug else 3


def _fmt_eur_range(lo: Optional[int], hi: Optional[int], *, per_month: bool = False) -> str:
    if lo and hi and lo != hi:
        core = f"€{lo:,}–€{hi:,}"
    elif hi:
        core = f"€{hi:,}"
    elif lo:
        core = f"€{lo:,}"
    else:
        core = "€—"
    return f"{core}/mo" if per_month else core


def _budget_reality_check(
    tags: List[str],
    scores: Dict[str, int],
    *,
    answers: Optional[Dict[str, Any]] = None,
    commune: Optional[Dict[str, Any]] = None,
    score_index: Optional[Dict[str, Dict[str, float]]] = None,
    score_dists: Optional[Dict[str, List[float]]] = None,
) -> str:
    """Generate an honest, non-numeric 'what you can expect' budget line.

    We avoid pretending we have market pricing data. Instead we provide a
    rule-of-thumb framing (bedroom range) and highlight uncertainty.
    """
    answers = answers or {}
    rent_lo, rent_hi = _parse_money_range(answers.get("budget_rent"))
    buy_lo, buy_hi = _parse_money_range(answers.get("budget_buy"))
    budgetfit = int(scores.get("BudgetFit", 3))

    # Commune cost pressure (same proxy as in BudgetFit; keeps messages commune-specific
    # without pretending we know exact prices).
    pressure_p = 0.5
    if commune and score_index:
        name = commune.get("name")
        base = score_index.get(name or "", {})
        pressure_raw = float(base.get("lifestyle", 0.0)) + 0.8 * float(base.get("commute", 0.0))
        dist = [float(r.get("lifestyle", 0.0)) + 0.8 * float(r.get("commute", 0.0)) for r in score_index.values()]
        pressure_p = _percentile_rank(dist, pressure_raw)

    pressure_txt = "more options" if pressure_p < 0.55 else ("moderate competition" if pressure_p < 0.8 else "tighter supply")

    if buy_hi:
        # Conservative, non-binding heuristic for BE apartments / townhouses
        buy_cap = buy_hi
        if buy_cap >= 950_000:
            target = "2–3BR (sometimes 4BR) depending on condition/building type"
        elif buy_cap >= 650_000:
            target = "2–3BR, depending on condition/building age"
        elif buy_cap >= 450_000:
            target = "1–2BR; 3BR becomes harder in prime streets"
        else:
            target = "studio–1BR; consider compromises on size or location"

        fit_txt = {
            5: "very comfortable",
            4: "generally workable",
            3: "workable with trade-offs",
            2: "likely tight",
            1: "very tight",
        }.get(budgetfit, "workable")

        amt = _fmt_eur_range(buy_lo, buy_hi)
        return (
            f"Rule of thumb for a {amt} purchase in this commune: target {target}. "
            f"Budget fit here is {fit_txt} with {pressure_txt}; verify listing density and condition during viewings."
        )

    if rent_hi:
        rent_cap = rent_hi
        if rent_cap >= 3200:
            target = "2–3BR apartments become realistic in many pockets"
        elif rent_cap >= 2300:
            target = "1–2BR apartments are typical; 3BR depends on compromise"
        elif rent_cap >= 1600:
            target = "studio–1BR is typical; 2BR depends on compromise"
        else:
            target = "studio-focused; consider widening the search"

        fit_txt = {
            5: "very comfortable",
            4: "generally workable",
            3: "workable with trade-offs",
            2: "likely tight",
            1: "very tight",
        }.get(budgetfit, "workable")

        amt = _fmt_eur_range(rent_lo, rent_hi, per_month=True)
        return (
            f"Rule of thumb for {amt} rent in this commune: {target}. "
            f"Budget fit here is {fit_txt} with {pressure_txt}; always confirm charges and indexation."
        )

    # No budget provided
    if "premium_feel" in tags:
        return "Prime pockets can be costly; confirm the full monthly cost (price/rent + charges + utilities)."
    return "Budget reality depends on the exact street and building condition; confirm total monthly cost early."


def _compute_scores_for_commune(
    commune: Dict[str, Any],
    score_index: Dict[str, Dict[str, float]],
    score_dists: Dict[str, List[float]],
    *,
    answers: Optional[Dict[str, Any]] = None,
    return_debug: bool = False,
) -> Any:
    name = commune.get("name")
    tags = commune.get("tags") or []
    base = score_index.get(name or "", {})

    # Percentile-based scaling (relative across communes) to avoid “all 5/5”.
    s_p = _percentile_rank(score_dists.get("safety", []), float(base.get("safety", 0.0)))
    f_p = _percentile_rank(score_dists.get("family", []), float(base.get("family", 0.0)))
    c_p = _percentile_rank(score_dists.get("commute", []), float(base.get("commute", 0.0)))
    l_p = _percentile_rank(score_dists.get("lifestyle", []), float(base.get("lifestyle", 0.0)))

    # Small deterministic bonuses/penalties based on tags
    safety_bonus = 0.4 if any(t in tags for t in ["older_quiet", "residential_quiet"]) else 0.0
    safety_pen = 0.5 if any(t in tags for t in ["night_caution", "nightlife", "busy_traffic_noise"]) else 0.0

    commute_bonus = 0.3 if any(t in tags for t in ["metro_strong", "tram_strong", "train_hubs_access"]) else 0.0
    commute_pen = 0.3 if "car_friendly" not in tags and "busy_traffic_noise" in tags else 0.0

    lifestyle_bonus = 0.2 if any(t in tags for t in ["cafes_brunch", "restaurants", "culture_museums"]) else 0.0
    family_bonus = 0.3 if any(t in tags for t in ["families", "schools_strong", "childcare_strong", "green_parks"]) else 0.0

    def _p_to_score(p: float) -> int:
        """Convert percentile to a realistic 2..5 score using bins."""
        if p < 0.25:
            return 2
        if p < 0.55:
            return 3
        if p < 0.8:
            return 4
        return 5

    # Map percentile -> 2..5, then apply tiny deterministic bumps.
    # IMPORTANT: Safety should very rarely be 5/5 for *all* communes (trust issue).
    # We therefore cap Safety at 4/5 unless the commune is in the top safety band.
    safety = _p_to_score(s_p)
    if safety_bonus > 0:
        safety += 1
    if safety_pen > 0:
        safety -= 1
    safety = max(2, min(5, safety))
    if safety >= 5 and s_p < 0.85:
        safety = 4

    family = _clamp_2_5(_p_to_score(f_p) + (1 if family_bonus > 0 else 0))

    # If the user's household is explicitly family-oriented, keep the family score conservative-but-plausible.
    # This prevents obvious UX mismatches like "family-friendly area" but Family=3/5 for green, school-heavy communes.
    h_txt = str(answers.get("household") or answers.get("household_type") or answers.get("family") or "").lower()
    kids_raw = answers.get("children_count", answers.get("kids_count", answers.get("children", answers.get("kids", 0))))
    try:
        kids_n = int(kids_raw) if str(kids_raw).strip() else 0
    except Exception:
        kids_n = 0
    is_family_household = ("family" in h_txt) or (kids_n > 0)
    if is_family_household and any(t in tags for t in ("families", "schools_strong", "childcare_strong", "green_parks")):
        family = max(family, 4)
    commute = _clamp_2_5(_p_to_score(c_p) + (1 if commute_bonus > 0 else 0) - (1 if commute_pen > 0 else 0))
    lifestyle = _clamp_2_5(_p_to_score(l_p) + (1 if lifestyle_bonus > 0 else 0))

    budget, budget_debug = _compute_budget_fit(
        tags,
        answers=answers,
        commune=commune,
        score_index=score_index,
        score_dists=score_dists,
        return_debug=True,
    )

    overall = int(round((safety + family + commute + lifestyle + budget) / 5.0))
    scores = {
        "Safety": safety,
        "Family": family,
        "Commute": commute,
        "Lifestyle": lifestyle,
        "BudgetFit": budget,
        "Overall": overall,
    }

    if not return_debug:
        return scores

    debug = {
        "name": name,
        "percentiles": {
            "Safety": s_p,
            "Family": f_p,
            "Commute": c_p,
            "Lifestyle": l_p,
        },
        "tag_adjustments": {
            "safety_bonus": safety_bonus,
            "safety_pen": safety_pen,
            "commute_bonus": commute_bonus,
            "commute_pen": commute_pen,
            "lifestyle_bonus": lifestyle_bonus,
            "family_bonus": family_bonus,
        },
        "budget": budget_debug,
        "scores": scores,
        "model": SCORE_MODEL,
    }
    return scores, debug


def _enforce_communes_and_microhoods(
    brief: Dict[str, Any],
    pack: Optional[Dict[str, Any]],
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not pack:
        return brief

    communes = pack.get("communes") or []
    if not communes:
        return brief

    # City label used for keyword fallbacks and copy; avoid NameError if not provided
    city_name = _as_str((answers or {}).get('city') or brief.get('city') or (pack or {}).get('city') or 'Brussels')

    # Allowed communes
    allowed = [c.get("name") for c in communes if c.get("name")]
    allowed_norm = {_norm_label(n): n for n in allowed}
    commune_by_name = {c.get("name"): c for c in communes if c.get("name")}

    # Scoring and geo validators
    score_index, score_dists = _build_commune_score_index(pack)
    microhood_commune = _load_microhood_commune_map()
    microhood_profiles = pack.get("microhood_profiles") or {}
    microhood_profiles_norm = {_norm_label(k): v for k, v in microhood_profiles.items() if isinstance(k, str) and isinstance(v, dict)}

    # If a microhood name looks like it belongs to a different commune (e.g. "Jette Centre"),
    # drop it to avoid perception issues even when the geojson doesn't provide a mapping.
    commune_tokens = {c: set(_norm_label(c).split()) for c in allowed}

    def _sent_end(t: str) -> str:
        t = _as_str(t).strip()
        if not t:
            return ""
        if t.endswith((".", "!", "?")):
            return t
        return t + "."

    def _microhood_highlights_for(nm: str, commune_obj: Dict[str, Any]) -> str:
        """Return a microhood-specific 2–3 sentence blurb.

        We prefer curated microhood profiles from the city-pack (deterministic and unique).
        If a profile is missing, we fall back to metrics-based heuristics.
        """
        prof = microhood_profiles_norm.get(_norm_label(nm)) or {}
        why_p = _sent_end(prof.get("why", ""))
        watch_p = _sent_end(prof.get("watch_out", ""))
        if why_p or watch_p:
            return " ".join([b for b in [why_p, watch_p] if b][:3]).strip()

        mh_obj = next(
            (m for m in (commune_obj.get("microhoods") or []) if isinstance(m, dict) and _norm_label(_as_str(m.get("name"))) == _norm_label(nm)),
            {},
        )
        why_m, watch_m = _microhood_sentence_from_metrics(mh_obj if isinstance(mh_obj, dict) else {})
        return f"{_sent_end(why_m)} {_sent_end(watch_m)}".strip()

    def _mk_microhood_entry(nm: str, commune_obj: Dict[str, Any], city_label: str) -> Dict[str, Any]:
        kw_raw = [nm, nm.replace(" / ", " "), nm.replace("-", " "), city_label]
        portal_keywords = _dedupe_str_list(kw_raw)[:4]
        return {
            "name": nm,
            "portal_keywords": portal_keywords,
            "highlights": _microhood_highlights_for(nm, commune_obj),
        }

    def _belongs_to_other_commune(mh_name: str, current_commune: str) -> bool:
        mh_norm = _norm_label(mh_name)
        for other in allowed:
            if other == current_commune:
                continue
            # strong signal: the other commune name (or a key token) is embedded in the microhood label
            if _norm_label(other) in mh_norm:
                return True
            toks = commune_tokens.get(other) or set()
            if toks and len(toks) == 1:
                t = next(iter(toks))
                if len(t) >= 5 and t in mh_norm:
                    return True
        return False

    def _is_landmark_like_microhood(mh_obj: Dict[str, Any]) -> bool:
        """Heuristic filter: avoid recommending parks/forests as "microhoods".

        Some monitoring zones are very large green areas (e.g., Forêt de Soignes).
        They are useful as anchors, but not as search-zones in property listings.
        """
        if not isinstance(mh_obj, dict):
            return True
        nm = _as_str(mh_obj.get("name"))
        n = _norm_label(nm)
        if any(k in n for k in ["foret", "forêt", "forest", "parc", "park", "bois", "cemet", "cimet"]):
            # allow known residential microhoods that contain one of these words (rare)
            # if they also have meaningful amenity density.
            m = mh_obj.get("metrics") or {}
            cafes = float(m.get("cafes_density") or 0)
            rest = float(m.get("restaurant_density") or m.get("restaurants_density") or 0)
            if cafes + rest < 2.0:
                return True
        m = mh_obj.get("metrics") or {}
        area = float(m.get("area_km2") or 0)
        parks_share = float(m.get("parks_share") or 0)
        # Very large zones with high parks share are anchors, not microhoods.
        if area >= 5.0 and parks_share >= 0.12:
            return True
        return False

    # Tenure mode (affects phrasing and some checklists)
    buy_lo, buy_hi = _parse_money_range((answers or {}).get("budget_buy"))
    rent_lo, rent_hi = _parse_money_range((answers or {}).get("budget_rent"))
    tenure = "buy" if (buy_hi or "buy" in _as_str((answers or {}).get("housing_type")).lower()) else "rent"

    # Desired priorities (for "matched_priorities")
    priority_ids = _split_csv((answers or {}).get("priority_tag_ids", ""))
    top3_ids = _split_csv((answers or {}).get("priority_top3_ids", ""))

    td_in = brief.get("top_districts")
    if not isinstance(td_in, list):
        td_in = []

    fixed: List[Dict[str, Any]] = []
    used = set()
    for it in td_in:
        if not isinstance(it, dict):
            continue
        raw_name = _as_str(it.get("name") or it.get("area"))
        name = allowed_norm.get(_norm_label(raw_name))
        if not name:
            # pick next unused
            name = next((n for n in allowed if n not in used), None)
        if not name:
            continue
        used.add(name)

        commune = commune_by_name.get(name, {})
        tags = commune.get("tags") or []
        # Always compute scores deterministically from city-pack metrics + budget.
        # This prevents "everything is 5/5" and improves trust.
        scores, score_debug = _compute_scores_for_commune(
            commune,
            score_index,
            score_dists,
            answers=answers,
            return_debug=True,
        )

        # Why / watch-out lists
        why = _trim(_as_list(it.get("why")), LIMITS["district_why"])
        watch = _trim(_as_list(it.get("watch_out")), LIMITS["district_watch"])
        if len(why) < 2:
            # Keep at least two bullets
            first_mh = None
            for mh in (commune.get("microhoods") or []):
                if isinstance(mh, dict) and mh.get("name"):
                    first_mh = _as_str(mh.get("name")).strip()
                    break
            anchor = first_mh or "key local hubs"
            why = (why + [f"Strong fit for your priorities around {anchor}.", "Balanced trade-off between lifestyle and commute."])[:2]
        if len(watch) < 1:
            hint = _as_str(commune.get("watch_out_hint"))
            watch = [hint or "Verify street-level noise/parking before shortlisting."]

        # Microhoods: strictly two-level hierarchy Commune → Microhood.
        # We only recommend microhoods from the city pack (monitoring zones), no separate "anchors" layer.
        mh_candidates: List[str] = []
        for mh in (commune.get("microhoods") or []):
            if not isinstance(mh, dict) or not mh.get("name"):
                continue
            if _is_landmark_like_microhood(mh):
                continue
            nm = _as_str(mh.get("name")).strip()
            if not nm:
                continue
            # Validate commune ownership (geojson) when possible
            mapped = microhood_commune.get(_norm_label(nm))
            if mapped and mapped != name:
                continue
            if _belongs_to_other_commune(nm, name):
                continue
            if nm not in mh_candidates:
                mh_candidates.append(nm)
            if len(mh_candidates) >= 3:
                break

        # Ensure at least 2
        if len(mh_candidates) < 2:
            for mh in (commune.get("microhoods_all") or []):
                if not isinstance(mh, dict) or not mh.get("name"):
                    continue
                if _is_landmark_like_microhood(mh):
                    continue
                nm = _as_str(mh.get("name")).strip()
                if not nm or nm in mh_candidates:
                    continue
                mapped = microhood_commune.get(_norm_label(nm))
                if mapped and mapped != name:
                    continue
                if _belongs_to_other_commune(nm, name):
                    continue
                mh_candidates.append(nm)
                if len(mh_candidates) >= 2:
                    break

        city_label = _as_str(pack.get("city_name") or pack.get("city") or answers.get("city") or "Brussels").strip()

        out_mh = [_mk_microhood_entry(nm, commune, city_label) for nm in mh_candidates[:2]]
        while len(out_mh) < 2:
            out_mh.append(_mk_microhood_entry(f"Area {len(out_mh)+1}", commune, city_label))

        top_microhoods = [m.get("name") for m in out_mh if isinstance(m, dict) and m.get("name")][:2]

        # Derive short, user-facing helpers used by the PDF renderer.
        # These MUST be computed before we append; otherwise missing optional
        # fields can cause UnboundLocalError at runtime.
        snapshot = _priority_snapshot(tags, scores, metrics=commune.get("metrics") or {})

        # Budget reality is computed from user answers + scores; keep this call
        # aligned with the helper signature.
        budget_reality = _budget_reality_check(
            tags=tags,
            scores=scores,
            answers=answers,
            commune=commune,
            score_index=score_index,
        )

        strengths, tradeoffs = _derive_strengths_tradeoffs(
            tags=tags,
            snapshot=commune.get("snapshot", {}) or {},
            anchors=top_microhoods,
            scores=scores,
            tenure=tenure,
        )

        fixed.append(
            {
                "name": name,
                "scores": scores,
                "score_debug": score_debug,
                "why": why,
                "watch_out": watch,
                "strengths": strengths,
                "tradeoffs": tradeoffs,
                "matched_priorities": _priority_match(tags, priority_ids, top3_ids),
                "priority_snapshot": snapshot,
                "budget_reality": budget_reality,
                "top_microhoods": top_microhoods,
                "microhoods": out_mh,
            }
        )

    # pad to 3 communes if needed
    for n in allowed:
        if len(fixed) >= 3:
            break
        if n in used:
            continue

        commune = commune_by_name.get(n, {})
        tags = commune.get("tags") or []
        scores, score_debug = _compute_scores_for_commune(
            commune,
            score_index,
            score_dists,
            answers=answers,
            return_debug=True,
        )
        why = ["Strong fit for your stated priorities.", "Balanced trade-off between lifestyle and commute."]
        hint = _as_str(commune.get("watch_out_hint"))
        watch = [hint or "Verify street-level noise/parking before shortlisting."]

        mh_candidates: List[str] = []
        for mh in (commune.get("microhoods") or []):
            if not isinstance(mh, dict) or not mh.get("name"):
                continue
            if _is_landmark_like_microhood(mh):
                continue
            nm = _as_str(mh.get("name")).strip()
            if not nm:
                continue
            mapped = microhood_commune.get(_norm_label(nm))
            if mapped and mapped != n:
                continue
            if _belongs_to_other_commune(nm, n):
                continue
            if nm not in mh_candidates:
                mh_candidates.append(nm)
            if len(mh_candidates) >= 2:
                break

        city_label = _as_str(pack.get("city_name") or pack.get("city") or answers.get("city") or "Brussels").strip()

        out_mh = [_mk_microhood_entry(nm, commune, city_label) for nm in mh_candidates[:2]]
        while len(out_mh) < 2:
            out_mh.append(_mk_microhood_entry(f"Area {len(out_mh)+1}", commune, city_label))

        top_microhoods = [m.get("name") for m in out_mh if isinstance(m, dict) and m.get("name")][:2]
        snapshot = _priority_snapshot(tags, scores, metrics=commune.get("metrics") or {})
        budget_reality = _budget_reality_check(
            tags=tags,
            scores=scores,
            answers=answers,
            commune=commune,
            score_index=score_index,
        )
        strengths, tradeoffs = _derive_strengths_tradeoffs(
            tags=tags,
            snapshot=commune.get("snapshot", {}) or {},
            anchors=top_microhoods,
            scores=scores,
            tenure=tenure,
        )
        fixed.append(
            {
                "name": n,
                "scores": scores,
                "score_debug": score_debug,
                "why": why,
                "watch_out": watch,
                "strengths": strengths,
                "tradeoffs": tradeoffs,
                "matched_priorities": _priority_match(tags, priority_ids, top3_ids),
                "priority_snapshot": snapshot,
                "budget_reality": budget_reality,
                "top_microhoods": top_microhoods,
                "microhoods": out_mh,
            }
        )


    fixed_sorted = sorted(
        fixed,
        key=lambda d: (
            int(d.get("scores", {}).get("Overall", 0)),
            int(d.get("scores", {}).get("Family", 0)),
            int(d.get("scores", {}).get("BudgetFit", 0)),
        ),
        reverse=True,
    )
    # Guarantee top-3 sorted by Overall (tie-break Family, BudgetFit)
    brief["top_districts"] = fixed_sorted[:3]
    return brief


def normalize_brief(
    brief: Any,
    *,
    city: str | None = None,
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    # Basic shape
    if not isinstance(brief, dict):
        brief = {"client_profile": _as_str(brief)}

    answers = answers or {}
    buy_lo, buy_hi = _parse_money_range(answers.get("budget_buy"))
    is_buy = bool(buy_hi or ("buy" in _as_str(answers.get("housing_type")).lower()))

    out: Dict[str, Any] = {}

    out["client_profile"] = _as_str(brief.get("client_profile", ""))[: LIMITS["client_profile_chars"]]
    out["must_have"] = _trim(_as_list(brief.get("must_have")), LIMITS["must_have"])
    out["nice_to_have"] = _trim(_as_list(brief.get("nice_to_have")), LIMITS["nice_to_have"])
    out["red_flags"] = _trim(_as_list(brief.get("red_flags")), LIMITS["red_flags"])
    out["contradictions"] = _trim(_as_list(brief.get("contradictions")), LIMITS["contradictions"])
    out["questions_for_agent_landlord"] = _trim(
        _as_list(brief.get("questions_for_agent_landlord")),
        LIMITS["questions"],
    )
    out["next_steps"] = _trim(_as_list(brief.get("next_steps")), LIMITS["next_steps"])
    out["clarifying_questions"] = _trim(
        _as_list(brief.get("clarifying_questions")),
        LIMITS["clarifying_questions"],
    )

    # If the model provided too few steps, expand deterministically.
    if len(out["next_steps"]) < 8:
        default_steps_buy = [
            "Shortlist 8–12 listings across the 3 communes and set up viewings.",
            "Confirm total purchase cost: price + notary/registration fees + recurring charges.",
            "Validate commute: run one test route at peak hours (public transport and by car if relevant).",
            "Ask about parking (permit vs private spot), storage, and building rules.",
            "Prepare a document pack for offers: ID, proof of funds/pre-approval, and key questions for the seller.",
            "Request EPC, urbanism/permit docs, and recent syndic/HOA minutes before committing.",
            "Do an evening walk-through for your top 2 choices to assess noise and street feel.",
            "Plan your notary steps and financing timeline; align deed date with your move plan.",
            "Book a second visit with measurements/photos to compare objectively.",
            "If needed, line up a survey/technical inspection for building issues.",
        ]
        default_steps_rent = [
            "Shortlist 8–12 listings across the 3 communes and set up viewings.",
            "Confirm total monthly cost: rent + charges + utilities (and what's included).",
            "Validate commute: run one test route at peak hours (public transport and by car if relevant).",
            "Ask about parking rules/permits and bike/storage options.",
            "Prepare a rental document pack: ID, proof of income, employer letter, bank statements.",
            "For the top 2 options, do an evening walk-through to assess noise and safety.",
            "Clarify contract length, notice period, indexation, and deposit rules.",
            "Book a second visit with measurements and photos to compare objectively.",
            "Pre-validate a rental guarantee to move fast on good listings.",
            "Confirm handover checklist and inventory (appliances/fixtures) in writing.",
        ]
        out["next_steps"] = (
            out["next_steps"]
            + (default_steps_buy if is_buy else default_steps_rent)
        )[: LIMITS["next_steps"]]

    # Practical checklists (for 'act tomorrow')
    if "viewing_checklist" not in out:
        out["viewing_checklist"] = [
            "Noise: check windows closed/open, street vs courtyard orientation.",
            "Heating & insulation: type, EPC score, drafts, humidity/mold signs.",
            "Charges: what's included (common areas, heating, water) and past statements.",
            "Building works: planned renovations, roof/façade, lift, syndic notes.",
            "Internet/cell coverage: quick speed test on site.",
            "Storage: cellar, bike room, stroller access, elevator size.",
            "Parking: permit eligibility, private spot, guest parking, EV charging.",
            "Safety basics: entrance, lighting, intercom, visibility at night.",
        ]
        if is_buy:
            out["viewing_checklist"] += [
                "Documents: EPC, urbanism/permit info, recent syndic/HOA minutes.",
                "Total budget: mortgage + recurring charges + utilities + insurance + taxes.",
            ]
        else:
            out["viewing_checklist"] += [
                "Appliances/fixtures: inventory list and condition (rental check-in).",
                "Total budget: rent + charges + utilities + insurance.",
            ]
    else:
        # Sanitize generic lines that confuse buy vs rent mode.
        vc = _as_list(out.get("viewing_checklist"))
        cleaned = []
        for line in vc:
            l = _as_str(line)
            low = _norm_label(l)
            if "appliances/fixtures" in low:
                if is_buy:
                    continue
                cleaned.append("Appliances/fixtures: inventory list and condition (rental check-in).")
                continue
            if low.startswith("total budget"):
                cleaned.append(
                    "Total budget: mortgage + recurring charges + utilities + insurance + taxes." if is_buy else "Total budget: rent + charges + utilities + insurance."
                )
                continue
            cleaned.append(l)
        out["viewing_checklist"] = cleaned
    out.setdefault(
        "offer_strategy",
        [
            "Move quickly on strong listings: good units can disappear within days.",
            "Clarify conditions (financing, sale of current property) early; keep them realistic.",
            "Ask for EPC, urbanism info, and syndic documents before committing (buying).",
            "Confirm timelines: offer validity, deed date (buying) or move-in date (renting).",
            "Negotiate on total package: included furniture, repairs, parking spot, charges.",
        ],
    )

    # Relocation essentials (operational steps beyond real estate)
    out.setdefault(
        "relocation_essentials",
        {
            "first_72h": [
                "Set up a local SIM / data plan and enable 2FA for banking.",
                "Confirm temporary address and keep copies of the lease / purchase agreement.",
                "Book commune appointment for registration (as soon as address is confirmed).",
            ],
            "first_2_weeks": [
                "Register at the commune (address registration); follow up on police check if required.",
                "Choose a GP (médecin généraliste) and register with a mutualité (health fund).",
                "Arrange energy + internet contracts if not included (electricity/gas/internet).",
                "If you have a child: shortlist daycare/schools and start the application process.",
            ],
            "first_2_months": [
                "Set up a Belgian bank account if needed and update payroll details.",
                "Review insurance (home contents, liability); confirm coverage start date.",
                "If driving: confirm parking permit process, resident rules, and any LEZ requirements.",
            ],
        },
    )

    # Sanitize relocation-essentials copy to avoid confusing instructions.
    # (Example: "Pick 1–2 communes" is misleading; you register in the commune of residence.)
    essentials = out.get("relocation_essentials")
    if isinstance(essentials, dict):
        for k in ["first_72h", "first_2_weeks", "first_2_months"]:
            items = _as_list(essentials.get(k))
            fixed_items: List[str] = []
            for it in items:
                s = _as_str(it)
                s_norm = _norm_label(s)
                if "pick 1" in s_norm and "commune" in s_norm:
                    fixed_items.append("Once your address is confirmed, register in the commune of residence (appointment-based).")
                    continue
                fixed_items.append(s)
            essentials[k] = fixed_items
        out["relocation_essentials"] = essentials

    # Relocation admin checklist (kept high-level to avoid false precision)
    out.setdefault(
        "registration_checklist",
        [
            "Valid passport/ID + visa/residence documents (if applicable).",
            "Proof of address: signed lease / deed / housing attestation.",
            "Civil status docs if relevant (marriage/birth certificates) — bring originals and copies.",
            "Work proof: contract or employer letter (useful for some registrations).",
            "Keep digital scans of all documents and a folder for commune appointments.",
            "Confirm appointment booking channel (commune website/IRISbox when applicable) and required forms.",
        ],
    )

    # Determine city pack
    city_key = (city or _as_str(brief.get("city")) or _as_str((answers or {}).get("city"))).strip()
    pack = load_city_pack(city_key)

    # Enforce top_districts + microhoods from pack only
    out["top_districts"] = brief.get("top_districts")
    out = _enforce_communes_and_microhoods(out, pack, answers=answers)

    # Always take resources from the city pack for Belgium (stable list).
    # Support both the legacy structure (real_estate_sites / agencies) and
    # the new `resources` wrapper.
    if pack:
        res = pack.get("resources") or {}
        out["real_estate_sites"] = _norm_links(res.get("websites") or pack.get("real_estate_sites"))[:3]
        out["agencies"] = _norm_links(res.get("agencies") or pack.get("agencies"))[:5]
    else:
        out["real_estate_sites"] = _norm_links(brief.get("real_estate_sites"))
        out["agencies"] = _norm_links(brief.get("agencies"))

    # Methodology (helps trust): keep it short and deterministic.
    top3 = [d.get("name") for d in (out.get("top_districts") or []) if isinstance(d, dict) and d.get("name")]
    priority_ids = _split_csv((answers or {}).get("priority_tag_ids", ""))
    priority_top3 = _split_csv((answers or {}).get("priority_top3_ids", ""))
    meth_inputs = []
    if (answers or {}).get("housing_type"):
        meth_inputs.append(f"Housing type: {(answers or {}).get('housing_type')}")
    if (answers or {}).get("budget_rent"):
        meth_inputs.append(f"Budget (rent): {(answers or {}).get('budget_rent')}")
    if (answers or {}).get("budget_buy"):
        meth_inputs.append(f"Budget (buy): {(answers or {}).get('budget_buy')}")
    if (answers or {}).get("office_commute"):
        meth_inputs.append(f"Work commute: {(answers or {}).get('office_commute')}")
    if (answers or {}).get("school_commute"):
        meth_inputs.append(f"School commute: {(answers or {}).get('school_commute')}")

    out["methodology"] = {
        "inputs": meth_inputs[:6],
        "matching": [
            "We only recommend communes and microhoods from the city pack (no invented areas).",
            "Scores are computed from city-pack signals (amenities, transport, parks) + your budget.",
            f"Priority tags matched: {', '.join(priority_top3 or priority_ids[:3]) or '—' }.",
            f"Shortlist produced: {', '.join(top3) or '—' }.",
        ],
    }

    # Reduce copy/paste feel across the shortlist (UX/Copy).
    try:
        _uniqueize_shortlist_copy(out.get("top_districts") or [], answers=answers)
    except Exception:
        pass

    def _strip_ellipsis(text: str) -> str:
        # Executive summary must never show literal ellipsis characters.
        # If upstream copy contains them, strip and re-punctuate.
        t = _as_str(text).replace("…", "").strip()
        return t

    def _first_clause(text: str) -> str:
        """Return a short, complete clause.

        We prefer ending at strong punctuation (.) or (;), then (,).
        We NEVER append an ellipsis.
        """
        t = _strip_ellipsis(text)
        if not t:
            return "—"

        # Remove parenthetical noise which often makes phrases too long.
        t = re.sub(r"\s*\([^)]*\)", "", t).strip()

        # Prefer a full first sentence if available.
        for sep in [".", ";", ":"]:
            if sep in t:
                chunk = t.split(sep, 1)[0].strip()
                if chunk:
                    return chunk.rstrip(" ,;") + "."

        # Else, cut at the first comma (still a complete clause).
        if "," in t:
            chunk = t.split(",", 1)[0].strip()
            if chunk:
                return chunk.rstrip(" ,;") + "."

        # Already short-ish; ensure it ends cleanly.
        return t.rstrip(" ,;") + ("." if not t.endswith((".", "!", "?")) else "")

    # Executive summary lines for quick scanning (no copy/paste from cards).
    out["executive_summary"] = []
    for d in (out.get("top_districts") or [])[:3]:
        if not isinstance(d, dict):
            continue
        name = _as_str(d.get("name"))
        strengths = _as_list(d.get("strengths"))
        tradeoffs = _as_list(d.get("tradeoffs"))
        microhoods = [
            _as_str(x) for x in (d.get("top_microhoods") or []) if _as_str(x)
        ][:2]
        keywords = []
        mp = d.get("matched_priorities") or {}
        if isinstance(mp, dict):
            keywords = _dedupe_str_list((mp.get("strong") or []) + (mp.get("medium") or []))[:4]

        # Executive summary: MUST be short, complete, and never truncated with "…".
        # We derive a single complete clause for each column.
        best_for = _first_clause(strengths[0] if strengths else "—")
        watch_out = _first_clause(tradeoffs[0] if tradeoffs else "—")

        out["executive_summary"].append(
            {
                "name": name,
                "best_for": best_for,
                "watch_out": watch_out,
                "top_microhoods": microhoods,
                "keywords": keywords,
            }
        )

    # Final consistency + lint
    out = _postprocess_brief(out)
    out, warnings = run_quality_gate(out)
    out["quality_warnings"] = warnings

    return out
