"""Microhood ranking engine.

Selects top microhoods (monitoring zones) strictly *within a chosen commune*
using user-selected priority tags.

The engine is designed to be:
- deterministic (no LLM)
- explainable (produces a debug breakdown)
- scalable (new tags are defined in tag_registry.py; new cities supply metrics)
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from .tag_registry import TAG_REGISTRY, TagDef, get_tag_def


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_div(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return a / b


def _percentile(value: float, values: List[float]) -> float:
    """Percentile in [0, 1]."""
    if not values:
        return 0.0
    # stable behaviour even with duplicates
    less = sum(1 for x in values if x < value)
    eq = sum(1 for x in values if x == value)
    return _safe_div(less + 0.5 * eq, len(values))


def _derived_metric(name: str, metrics: Dict[str, Any]) -> float:
    """Derived metrics that are not stored directly in city packs."""
    if name == "amenity_density":
        return (
            _as_float(metrics.get("cafes_density"))
            + _as_float(metrics.get("restaurants_density"))
            + _as_float(metrics.get("bars_density"))
        )
    if name == "transit_density":
        return (
            _as_float(metrics.get("metro_density"))
            + _as_float(metrics.get("tram_density"))
            + _as_float(metrics.get("train_density"))
        )
    if name == "urban_dense_proxy":
        # dense urban areas tend to have both transit and amenities
        return 0.6 * _derived_metric("transit_density", metrics) + 0.4 * _derived_metric("amenity_density", metrics)
    return _as_float(metrics.get(name))


def _signal_value(metric_key: str, metrics: Dict[str, Any]) -> float:
    # allow derived metrics
    if metric_key in ("amenity_density", "transit_density", "urban_dense_proxy"):
        return _derived_metric(metric_key, metrics)
    return _as_float(metrics.get(metric_key))


def _tag_affinity(
    tag_def: TagDef,
    mh_metrics: Dict[str, Any],
    dist: Dict[str, List[float]],
) -> Tuple[float, List[Dict[str, Any]]]:
    """Compute affinity in [0,1] for a tag, plus per-signal debug."""
    if not tag_def.signals:
        return 0.0, []

    total_w = 0.0
    acc = 0.0
    sig_dbg: List[Dict[str, Any]] = []
    for sig in tag_def.signals:
        w = float(sig.weight or 0.0)
        if w <= 0:
            continue

        raw = _signal_value(sig.metric, mh_metrics)
        values = dist.get(sig.metric) or []
        p = _percentile(raw, values)
        # "low" means prefer lower raw -> invert percentile
        if sig.direction == "low":
            p = 1.0 - p

        acc += w * p
        total_w += w
        sig_dbg.append({
            "metric": sig.metric,
            "direction": sig.direction,
            "weight": w,
            "raw": raw,
            "percentile": round(p, 4),
        })

    if total_w <= 0:
        return 0.0, sig_dbg
    return acc / total_w, sig_dbg


def _build_distribution(microhoods: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    """Build per-metric distributions within a commune."""
    dist: Dict[str, List[float]] = {}
    # include base metrics + derived
    metric_keys = set()
    for mh in microhoods:
        m = mh.get("metrics") or {}
        for k in m.keys():
            metric_keys.add(k)
    metric_keys |= {"amenity_density", "transit_density", "urban_dense_proxy"}

    for k in metric_keys:
        vals = []
        for mh in microhoods:
            m = mh.get("metrics") or {}
            vals.append(_signal_value(k, m))
        dist[k] = vals
    return dist


def rank_microhoods_for_commune(
    commune_obj: Dict[str, Any],
    *,
    priority_tag_ids: List[str],
    priority_top3_ids: List[str],
    limit: int = 2,
    diversity: bool = True,
) -> Tuple[List[str], Dict[str, Any]]:
    """Return top-N microhood names + debug.

    The ranking uses *all* selected tags:
    - top3 tags have higher weight
    - other selected tags still influence score
    """

    microhoods_all = [m for m in (commune_obj.get("microhoods_all") or []) if isinstance(m, dict) and m.get("name")]
    if not microhoods_all:
        # fallback to the older shortlist
        microhoods_all = [m for m in (commune_obj.get("microhoods") or []) if isinstance(m, dict) and m.get("name")]

    dist = _build_distribution(microhoods_all)

    # Weights: keep deterministic and easy to tune later.
    w_top = 1.0
    w_other = 0.55
    # Ensure stable order for tags
    selected_tags = []
    seen = set()
    for t in (priority_tag_ids or []):
        if not t or t in seen:
            continue
        seen.add(t)
        selected_tags.append(t)

    top3_set = set(priority_top3_ids or [])

    candidates: List[Dict[str, Any]] = []
    for mh in microhoods_all:
        m_metrics = mh.get("metrics") or {}
        mh_name = str(mh.get("name")).strip()
        # compute per-tag contributions
        contributions = []
        score = 0.0
        coverage_hits = 0
        for tag_id in selected_tags:
            tag_def = get_tag_def(tag_id)
            if not tag_def:
                # unknown tag: keep as 0 but still record
                contributions.append({"tag": tag_id, "weight": w_top if tag_id in top3_set else w_other, "affinity": 0.0, "signals": []})
                continue
            affinity, sig_dbg = _tag_affinity(tag_def, m_metrics, dist)
            # incorporate microhood tag confidence when present
            conf = (mh.get("tag_confidence") or {}).get(tag_id)
            conf_mult = 1.0
            if isinstance(conf, str):
                c = conf.lower().strip()
                if c == "high":
                    conf_mult = 1.08
                elif c == "medium":
                    conf_mult = 1.03
                elif c == "low":
                    conf_mult = 0.97
            affinity_adj = max(0.0, min(1.0, affinity * conf_mult))

            w = w_top if tag_id in top3_set else w_other
            score += w * affinity_adj
            if affinity_adj >= 0.6:
                coverage_hits += 1
            contributions.append({
                "tag": tag_id,
                "weight": w,
                "affinity": round(affinity_adj, 4),
                "confidence": conf or "n/a",
                "signals": sig_dbg,
            })

        # Encourage covering more tags, not just spiking on one.
        if selected_tags:
            coverage_ratio = coverage_hits / max(1, len(selected_tags))
            score += 0.25 * coverage_ratio
        candidates.append({
            "name": mh_name,
            "score": score,
            "coverage_hits": coverage_hits,
            "contributions": contributions,
        })

    candidates.sort(key=lambda x: (-x["score"], x["name"].casefold()))

    selected: List[Dict[str, Any]] = []
    if not candidates:
        return [], {"selected": [], "candidates": 0}

    # pick first
    selected.append(candidates[0])

    if limit > 1:
        if not diversity:
            selected.append(candidates[1])
        else:
            # choose 2nd with diversity penalty (avoid same top tags)
            first = candidates[0]
            first_top_tags = [c["tag"] for c in sorted(first["contributions"], key=lambda d: (-d["affinity"], d["tag"]))[:3]]
            best2 = None
            best2_score = -1e9
            for cand in candidates[1:]:
                top_tags = [c["tag"] for c in sorted(cand["contributions"], key=lambda d: (-d["affinity"], d["tag"]))[:3]]
                overlap = len(set(first_top_tags) & set(top_tags))
                penalty = 0.08 * overlap
                s2 = cand["score"] - penalty
                if s2 > best2_score:
                    best2_score = s2
                    best2 = cand
            if best2 is None and len(candidates) > 1:
                best2 = candidates[1]
            if best2:
                selected.append(best2)

    out_names = [s["name"] for s in selected[:limit]]

    debug = {
        "weights": {"top3": w_top, "other": w_other, "coverage_bonus_max": 0.25},
        "priority_tags": selected_tags,
        "priority_top3": list(priority_top3_ids or []),
        "candidates": len(candidates),
        "selected": selected[:limit],
    }
    return out_names, debug
