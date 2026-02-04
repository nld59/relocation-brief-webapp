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

    # Strip currency symbols and keep digits
    digits = re.sub(r"[^0-9]", "", s)
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _clamp_1_5(v: float) -> int:
    return max(1, min(5, int(round(v))))


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
) -> Tuple[List[str], List[str]]:
    """Generate market-sounding strengths/trade-offs from deterministic inputs."""

    anchors = [a for a in (anchors or []) if a]
    anchor_hint = anchors[0] if anchors else "key local hubs"

    strengths: List[str] = []
    tradeoffs: List[str] = []

    # Strengths
    if "expats_international" in tags:
        strengths.append("Strong international / expat ecosystem and services.")
    if "eu_quarter_access" in tags:
        strengths.append("Very convenient access to the EU Quarter and central corridors.")
    if "green_parks" in tags or "families" in tags or "residential_quiet" in tags:
        strengths.append("Good balance of residential feel and nearby green space.")
    if "cafes_brunch" in tags or "restaurants" in tags:
        strengths.append("Plenty of day-to-day amenities (cafés, restaurants) within walking distance.")
    if "metro_strong" in tags or "tram_strong" in tags:
        strengths.append("Reliable public transport coverage for everyday commuting.")

    # Snapshot-derived (keeps it grounded)
    if snapshot.get("commute_access"):
        strengths.append(f"Good access to {snapshot['commute_access']} from {anchor_hint}.")

    # Trade-offs
    if "busy_traffic_noise" in tags:
        tradeoffs.append("Traffic/noise can be noticeable on main arteries; shortlist street-by-street.")
    if "nightlife" in tags or "night_caution" in tags:
        tradeoffs.append("Busier evenings in hotspots; confirm noise levels during a late walk-through.")
    if "premium_feel" in tags:
        tradeoffs.append("Prime pockets can be pricey; compare total monthly cost (rent + charges).")
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


def _build_commune_score_index(pack: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Precompute raw feature scores for scaling across communes."""
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

    # mins/maxs
    def _minmax(key: str) -> Tuple[float, float]:
        vals = [r[1][key] for r in rows if r[0]]
        if not vals:
            return (0.0, 1.0)
        return (min(vals), max(vals))

    mn_l, mx_l = _minmax("lifestyle")
    mn_c, mx_c = _minmax("commute")
    mn_f, mx_f = _minmax("family")
    mn_s, mx_s = _minmax("safety")

    idx: Dict[str, Dict[str, float]] = {}
    for name, raw in rows:
        if not name:
            continue
        idx[name] = {
            "lifestyle_n": _norm_minmax(raw["lifestyle"], mn_l, mx_l),
            "commute_n": _norm_minmax(raw["commute"], mn_c, mx_c),
            "family_n": _norm_minmax(raw["family"], mn_f, mx_f),
            "safety_n": _norm_minmax(raw["safety"], mn_s, mx_s),
        }
    return idx


def _compute_budget_fit(tags: List[str], answers: Optional[Dict[str, Any]] = None) -> int:
    """Budget fit heuristic (1-5) based on user budget and 'premium' signals."""
    answers = answers or {}
    rent = _parse_money(answers.get("budget_rent"))
    buy = _parse_money(answers.get("budget_buy"))

    # Decide which budget we have
    budget = buy if buy else rent

    # If we don't have budget, return neutral
    if not budget:
        return 3

    premium = "premium_feel" in tags
    central = "central_access" in tags

    # Very rough tiers (Brussels): rent in EUR/mo, buy in EUR
    if rent and not buy:
        if premium or central:
            if rent >= 2800:
                return 4
            if rent >= 2200:
                return 3
            return 2
        # non-premium
        if rent >= 2000:
            return 4
        if rent >= 1500:
            return 3
        return 2
    if buy:
        if premium or central:
            if buy >= 850_000:
                return 4
            if buy >= 650_000:
                return 3
            return 2
        if buy >= 650_000:
            return 4
        if buy >= 450_000:
            return 3
        return 2

    return 3


def _compute_scores_for_commune(
    commune: Dict[str, Any],
    score_index: Dict[str, Dict[str, float]],
    *,
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    name = commune.get("name")
    tags = commune.get("tags") or []
    base = score_index.get(name or "", {})

    # IMPORTANT: keep the scale realistic.
    # A common user trust issue was "everything is 5/5".
    # We deliberately compress the upper end and only allow 5 in truly top cases.
    s_n = float(base.get("safety_n", 0.5))
    f_n = float(base.get("family_n", 0.5))
    c_n = float(base.get("commute_n", 0.5))
    l_n = float(base.get("lifestyle_n", 0.5))

    # Small deterministic bonuses/penalties based on tags
    safety_bonus = 0.4 if any(t in tags for t in ["older_quiet", "residential_quiet"]) else 0.0
    safety_pen = 0.5 if any(t in tags for t in ["night_caution", "nightlife", "busy_traffic_noise"]) else 0.0

    commute_bonus = 0.3 if any(t in tags for t in ["metro_strong", "tram_strong", "train_hubs_access"]) else 0.0
    commute_pen = 0.3 if "car_friendly" not in tags and "busy_traffic_noise" in tags else 0.0

    lifestyle_bonus = 0.2 if any(t in tags for t in ["cafes_brunch", "restaurants", "culture_museums"]) else 0.0
    family_bonus = 0.3 if any(t in tags for t in ["families", "schools_strong", "childcare_strong", "green_parks"]) else 0.0

    safety = _clamp_1_5(2.1 + 2.3 * s_n + safety_bonus - safety_pen)
    family = _clamp_1_5(2.0 + 2.4 * f_n + family_bonus)
    commute = _clamp_1_5(2.0 + 2.3 * c_n + commute_bonus - commute_pen)
    lifestyle = _clamp_1_5(2.0 + 2.3 * l_n + lifestyle_bonus)
    budget = _compute_budget_fit(tags, answers=answers)

    overall = int(round((safety + family + commute + lifestyle + budget) / 5.0))
    return {
        "Safety": safety,
        "Family": family,
        "Commute": commute,
        "Lifestyle": lifestyle,
        "BudgetFit": budget,
        "Overall": overall,
    }


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

    # Allowed communes
    allowed = [c.get("name") for c in communes if c.get("name")]
    allowed_norm = {_norm_label(n): n for n in allowed}
    commune_by_name = {c.get("name"): c for c in communes if c.get("name")}

    # Scoring and geo validators
    score_index = _build_commune_score_index(pack)
    microhood_commune = _load_microhood_commune_map()

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
        scores = _compute_scores_for_commune(commune, score_index, answers=answers)

        # Why / watch-out lists
        why = _trim(_as_list(it.get("why")), LIMITS["district_why"])
        watch = _trim(_as_list(it.get("watch_out")), LIMITS["district_watch"])
        if len(why) < 2:
            # Keep at least two bullets
            anchors = commune.get("micro_anchors") or []
            anchor = anchors[0] if anchors else "key local hubs"
            why = (why + [f"Strong fit for your priorities around {anchor}.", "Balanced trade-off between lifestyle and commute."])[:2]
        if len(watch) < 1:
            hint = _as_str(commune.get("watch_out_hint"))
            watch = [hint or "Verify street-level noise/parking before shortlisting."]

        # Micro-anchors: always take from pack (validator)
        micro_anchors = commune.get("micro_anchors") or []
        if not isinstance(micro_anchors, list):
            micro_anchors = []
        micro_anchors = [str(x).strip() for x in micro_anchors if str(x).strip()][:3]

        # Microhoods: validate microhood belongs to commune using monitoring geojson
        allowed_mh = []
        for mh in (commune.get("microhoods") or []):
            if not isinstance(mh, dict) or not mh.get("name"):
                continue
            nm = _as_str(mh.get("name"))
            owner = microhood_commune.get(_norm_label(nm))
            if owner and owner != name:
                continue
            allowed_mh.append(mh)
        allowed_mh_names = [mh.get("name") for mh in allowed_mh]
        allowed_mh_norm = {_norm_label(n): n for n in allowed_mh_names if n}

        out_mh: List[Dict[str, str]] = []
        mh_in = it.get("microhoods")
        if isinstance(mh_in, list):
            used_mh = set()
            for mho in mh_in[: LIMITS["microhoods"]]:
                if not isinstance(mho, dict):
                    continue
                nm_raw = _as_str(mho.get("name"))
                nm = allowed_mh_norm.get(_norm_label(nm_raw))
                if not nm:
                    nm = next((n for n in allowed_mh_names if n not in used_mh), None)
                if not nm:
                    continue
                used_mh.add(nm)

                mh_obj = next((m for m in allowed_mh if m.get("name") == nm), {})
                why_s = _as_str(mho.get("why"))
                watch_s = _as_str(mho.get("watch_out"))
                if not why_s or not watch_s:
                    gen_why, gen_watch = _microhood_sentence_from_metrics(mh_obj)
                    why_s = why_s or gen_why
                    watch_s = watch_s or gen_watch
                out_mh.append({"name": nm, "why": why_s[:160], "watch_out": watch_s[:160]})

        # Fill missing microhoods deterministically
        if len(out_mh) < 2 and allowed_mh:
            for mh_obj in allowed_mh:
                if len(out_mh) >= 2:
                    break
                nm = mh_obj.get("name")
                if any(x["name"] == nm for x in out_mh):
                    continue
                gen_why, gen_watch = _microhood_sentence_from_metrics(mh_obj)
                out_mh.append({"name": nm, "why": gen_why[:160], "watch_out": gen_watch[:160]})

        out_mh = out_mh[: LIMITS["microhoods"]]

        snapshot = _priority_snapshot(tags, scores, metrics=commune.get("metrics") or {})
        strengths, tradeoffs = _derive_strengths_tradeoffs(tags, snapshot, anchors=micro_anchors)

        fixed.append(
            {
                "name": name,
                "micro_anchors": micro_anchors,
                "scores": scores,
                "why": why,
                "watch_out": watch,
                "strengths": strengths,
                "tradeoffs": tradeoffs,
                "matched_priorities": _priority_match(tags, priority_ids, top3_ids),
                "priority_snapshot": snapshot,
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
        scores = _compute_scores_for_commune(commune, score_index, answers=answers)
        why = ["Strong fit for your stated priorities.", "Balanced trade-off between lifestyle and commute."]
        hint = _as_str(commune.get("watch_out_hint"))
        watch = [hint or "Verify street-level noise/parking before shortlisting."]
        micro_anchors = (commune.get("micro_anchors") or [])[:3]
        allowed_mh = []
        for mh in (commune.get("microhoods") or []):
            if not isinstance(mh, dict) or not mh.get("name"):
                continue
            nm = _as_str(mh.get("name"))
            owner = microhood_commune.get(_norm_label(nm))
            if owner and owner != n:
                continue
            allowed_mh.append(mh)
        out_mh = []
        for mh_obj in allowed_mh[:2]:
            gen_why, gen_watch = _microhood_sentence_from_metrics(mh_obj)
            out_mh.append({"name": mh_obj.get("name"), "why": gen_why[:160], "watch_out": gen_watch[:160]})
        snapshot = _priority_snapshot(tags, scores, metrics=commune.get("metrics") or {})
        strengths, tradeoffs = _derive_strengths_tradeoffs(tags, snapshot, anchors=[str(x).strip() for x in micro_anchors if str(x).strip()])
        fixed.append(
            {
                "name": n,
                "micro_anchors": [str(x).strip() for x in micro_anchors if str(x).strip()],
                "scores": scores,
                "why": why,
                "watch_out": watch,
                "strengths": strengths,
                "tradeoffs": tradeoffs,
                "matched_priorities": _priority_match(tags, priority_ids, top3_ids),
                "priority_snapshot": snapshot,
                "microhoods": out_mh,
            }
        )

    brief["top_districts"] = fixed[:3]
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
        out["next_steps"] = (
            out["next_steps"]
            + [
                "Schedule viewings across the 3 communes and keep notes in a single tracker.",
                "Confirm total monthly cost: rent + charges + utilities (and what's included).",
                "Test the commute at peak hours (public transport and/or car).",
                "Ask about parking rules/permits and bike/storage options.",
                "Prepare a document pack: ID, proof of income, employer letter, bank statements.",
                "For the top 2 options, do an evening walk-through to assess noise and safety.",
                "If buying: request EPC, urbanism/permit docs, and recent syndic/HOA minutes.",
                "If renting: clarify contract length, notice period, indexation, and deposit rules.",
                "Book a second visit with measurements and photos to compare objectively.",
                "Pre-validate financing (or a rental guarantee) to move fast on good listings.",
            ]
        )[: LIMITS["next_steps"]]

    # Practical checklists (for 'act tomorrow')
    out.setdefault(
        "viewing_checklist",
        [
            "Noise: check windows closed/open, street vs courtyard orientation.",
            "Heating & insulation: type, EPC score, drafts, humidity/mold signs.",
            "Charges: what's included (common areas, heating, water) and past statements.",
            "Building works: planned renovations, roof/façade, lift, syndic notes.",
            "Internet/cell coverage: quick speed test on site.",
            "Storage: cellar, bike room, stroller access, elevator size.",
            "Parking: permit eligibility, private spot, guest parking, EV charging.",
            "Safety basics: entrance, lighting, intercom, visibility at night.",
            "Appliances/fixtures: inventory list and condition (if renting).",
            "Total budget: rent/mortgage + charges + utilities + insurance.",
        ],
    )
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

    # Relocation essentials: action plan beyond real estate (first 72h / 2w / 2m).
    out["relocation_essentials"] = {
        "first_72h": [
            "Book temporary accommodation if needed and confirm the first viewing schedule.",
            "Prepare document scans (IDs, visas/residence, payslips/employer letter).",
            "Pick 1–2 communes for administrative steps (registration timing depends on your move date).",
        ],
        "first_2_weeks": [
            "Register at the commune (if applicable) and start the resident file (appointment-based).",
            "Choose a GP and check insurance coverage / mutuelle requirements.",
            "If family: shortlist schools/childcare and request availability/registration steps.",
            "Set up a Belgian phone plan and confirm internet availability at shortlisted addresses.",
        ],
        "first_2_months": [
            "Finalize utilities (energy/water) and update contracts after moving in.",
            "If buying: schedule notary steps, financing, and property checks (EPC, urbanism, syndic docs).",
            "Set up local services: bank, insurance, parking permit (if needed), and subscriptions.",
        ],
    }

    # Executive summary lines for quick scanning.
    out["executive_summary"] = []
    for d in (out.get("top_districts") or [])[:3]:
        if not isinstance(d, dict):
            continue
        out["executive_summary"].append(
            {
                "name": d.get("name"),
                "best_for": (d.get("strengths") or [])[:2],
                "watch": (d.get("tradeoffs") or [])[:1],
                "microhoods": [m.get("name") for m in (d.get("microhoods") or []) if isinstance(m, dict) and m.get("name")][:3],
            }
        )

    return out
