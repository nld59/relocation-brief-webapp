from __future__ import annotations

"""Deterministic commune ranking.

Primary ranking reflects the user's selected priorities (top-3 stronger), while
"Overall" remains a secondary (consistency) signal.

This module is city-agnostic: it ranks using the 5 dimension scores already
computed in normalize.py (Safety/Family/Commute/Lifestyle/BudgetFit).
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


DIMENSIONS = ("Safety", "Family", "Commute", "Lifestyle", "BudgetFit")


@dataclass(frozen=True)
class RankWeights:
    """Per-dimension weights (higher means more important)."""

    by_dim: Dict[str, float]
    # Debug information that can be surfaced to users/brokers.
    debug: Dict[str, object]


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def build_commune_rank_weights(
    *,
    priority_tag_ids: Sequence[str],
    priority_top3_ids: Sequence[str],
    # Tag → dimension affinity (kept in one place for easy future edits)
    tag_dim_map: Mapping[str, Mapping[str, float]],
    weight_top3: float = 1.0,
    weight_other: float = 0.55,
) -> RankWeights:
    """Convert selected tags into per-dimension weights.

    Every selected tag contributes to one or more dimensions.
    Top-3 tags contribute more.
    """

    top3 = {t for t in priority_top3_ids if t}
    selected = [t for t in priority_tag_ids if t]

    dim_w: Dict[str, float] = {d: 0.0 for d in DIMENSIONS}
    per_tag: Dict[str, Dict[str, float]] = {}

    for t in selected:
        affinity = dict(tag_dim_map.get(t, {}))
        if not affinity:
            continue
        base_w = weight_top3 if t in top3 else weight_other
        per_tag[t] = {}
        for d, a in affinity.items():
            if d not in dim_w:
                continue
            # a can be used to express stronger affinity than 1.0
            contrib = float(a) * float(base_w)
            dim_w[d] += contrib
            per_tag[t][d] = contrib

    # If user selected tags that don't map, fall back to balanced.
    if sum(dim_w.values()) <= 1e-9:
        dim_w = {d: 1.0 for d in DIMENSIONS}

    # Normalize weights to sum=1 for interpretability.
    s = sum(dim_w.values())
    dim_w_norm = {d: (dim_w[d] / s) for d in DIMENSIONS}

    debug = {
        "selected_tags": selected,
        "top3_tags": [t for t in priority_top3_ids if t],
        "raw_dim_weights": dim_w,
        "dim_weights": dim_w_norm,
        "per_tag_contrib": per_tag,
    }
    return RankWeights(by_dim=dim_w_norm, debug=debug)


def profile_score(scores: Mapping[str, int], weights: Mapping[str, float]) -> float:
    """Compute a 0..5 score by weighting the 5 dimension scores."""
    total = 0.0
    for d, w in weights.items():
        total += float(scores.get(d, 0)) * float(w)
    # scores are in 1..5, so total is also in 0..5
    return float(total)


def rank_communes(
    communes: List[Dict[str, object]],
    *,
    weights: RankWeights,
    # How much we allow a commune with much higher Overall to jump ahead
    # when profile scores are close.
    swap_overall_gap: int = 2,
    swap_profile_eps: float = 0.45,
) -> List[Dict[str, object]]:
    """Rank communes by profile score, then reconcile to avoid Overall contradictions.

    Input list items must include:
      - name: str
      - scores: dict with 5 dimensions + Overall
    """

    items: List[Dict[str, object]] = []
    for c in communes:
        sc = dict(c.get("scores") or {})
        ps = profile_score(sc, weights.by_dim)
        c2 = dict(c)
        c2["profile_score"] = ps
        items.append(c2)

    # Primary ordering: profile score, then Overall, then Family/Safety.
    items.sort(
        key=lambda d: (
            float(d.get("profile_score") or 0.0),
            int((d.get("scores") or {}).get("Overall", 0)),
            int((d.get("scores") or {}).get("Family", 0)),
            int((d.get("scores") or {}).get("Safety", 0)),
        ),
        reverse=True,
    )

    # Reconcile to reduce obvious contradictions:
    # If two adjacent communes have close profile scores, but the lower one has
    # Overall ahead by >= swap_overall_gap, swap them.
    swapped = True
    while swapped:
        swapped = False
        for i in range(len(items) - 1):
            a = items[i]
            b = items[i + 1]
            a_ps = float(a.get("profile_score") or 0.0)
            b_ps = float(b.get("profile_score") or 0.0)
            a_o = int((a.get("scores") or {}).get("Overall", 0))
            b_o = int((b.get("scores") or {}).get("Overall", 0))
            if (b_o - a_o) >= swap_overall_gap and (a_ps - b_ps) <= swap_profile_eps:
                items[i], items[i + 1] = items[i + 1], items[i]
                swapped = True

    # Attach ranking debug.
    for idx, c in enumerate(items, start=1):
        c["rank"] = idx
        c["rank_debug"] = {
            "profile_score": float(c.get("profile_score") or 0.0),
            "overall": int((c.get("scores") or {}).get("Overall", 0)),
            "weights": weights.debug,
        }

    return items
