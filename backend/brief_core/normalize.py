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


def _priority_snapshot(tags: List[str], scores: Dict[str, int]) -> Dict[str, str]:
    # Cost / budget feel
    bf = int(scores.get("BudgetFit", 3))
    if "premium_feel" in tags or bf <= 2:
        cost = "Higher cost; budget may feel tight in prime streets."
    elif "value_for_money" in tags or bf >= 4:
        cost = "Better value vs central premium areas; more space for the budget."
    else:
        cost = "Mid-range pricing; specific streets vary a lot."

    # Transit
    transit_bits = []
    if "metro_strong" in tags:
        transit_bits.append("strong metro")
    if "tram_strong" in tags:
        transit_bits.append("strong tram")
    if "train_hubs_access" in tags:
        transit_bits.append("easy train hubs")
    transit = ", ".join(transit_bits) if transit_bits else "more bus-based; verify nearest stops"

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
    if any(t in tags for t in ["families", "schools_strong", "childcare_strong", "green_parks"]):
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
        scores = _score_obj(it.get("scores") or {})
        # If LLM gave no scores, keep defaults, but Overall may still be OK.

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

        # Micro-anchors
        micro_anchors = commune.get("micro_anchors") or []
        if not isinstance(micro_anchors, list):
            micro_anchors = []
        micro_anchors = [str(x).strip() for x in micro_anchors if str(x).strip()][:3]

        # Microhoods
        allowed_mh = [
            mh for mh in (commune.get("microhoods") or [])
            if isinstance(mh, dict) and mh.get("name")
        ]
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

        fixed.append(
            {
                "name": name,
                "micro_anchors": micro_anchors,
                "scores": scores,
                "why": why,
                "watch_out": watch,
                "matched_priorities": _priority_match(tags, priority_ids, top3_ids),
                "priority_snapshot": _priority_snapshot(tags, scores),
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
        scores = _score_obj({})
        why = ["Strong fit for your stated priorities.", "Balanced trade-off between lifestyle and commute."]
        hint = _as_str(commune.get("watch_out_hint"))
        watch = [hint or "Verify street-level noise/parking before shortlisting."]
        micro_anchors = (commune.get("micro_anchors") or [])[:3]
        allowed_mh = [mh for mh in (commune.get("microhoods") or []) if isinstance(mh, dict) and mh.get("name")]
        out_mh = []
        for mh_obj in allowed_mh[:2]:
            gen_why, gen_watch = _microhood_sentence_from_metrics(mh_obj)
            out_mh.append({"name": mh_obj.get("name"), "why": gen_why[:160], "watch_out": gen_watch[:160]})
        fixed.append(
            {
                "name": n,
                "micro_anchors": [str(x).strip() for x in micro_anchors if str(x).strip()],
                "scores": scores,
                "why": why,
                "watch_out": watch,
                "matched_priorities": _priority_match(tags, priority_ids, top3_ids),
                "priority_snapshot": _priority_snapshot(tags, scores),
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

    # Determine city pack
    city_key = (city or _as_str(brief.get("city")) or _as_str((answers or {}).get("city"))).strip()
    pack = load_city_pack(city_key)

    # Enforce top_districts + microhoods from pack only
    out["top_districts"] = brief.get("top_districts")
    out = _enforce_communes_and_microhoods(out, pack, answers=answers)

    # Always take resources from pack for Belgium (stable list).
    # If pack not available, fallback to model output.
    if pack:
        out["real_estate_sites"] = _norm_links(pack.get("real_estate_sites"))[:3]
        out["agencies"] = _norm_links(pack.get("agencies"))[:5]
    else:
        out["real_estate_sites"] = _norm_links(brief.get("real_estate_sites"))
        out["agencies"] = _norm_links(brief.get("agencies"))

    return out
