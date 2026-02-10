"""Quality gate for normalized briefs.

This module provides lightweight lint + safe auto-fixes to prevent recurring
data/presentation issues in the premium PDF.

The gate is intentionally:
- deterministic
- non-fatal (returns warnings)
- conservative (only safe auto-fixes)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _norm_dashes(s: str) -> str:
    s = s or ""
    # Remove unicode joiners/no-break spaces that can show up as black squares in PDFs.
    s = (
        s.replace(" ", " ")
        .replace(" ", " ")
        .replace(" ", " ")
        .replace("⁠", "")
        .replace("​", "")
        .replace("﻿", "")
        .replace("‑", "-")
        .replace("‐", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("■", "-")
        .replace("□", "-")
        .replace("▪", "-")
        .replace("▫", "-")
    )
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _strip_near_prefix(s: str) -> str:
    s = s or ""
    return re.sub(r"^Near\s+", "", s, flags=re.I).strip()


def _dedupe_ci(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for it in items or []:
        s = (it or "").strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def run_quality_gate(brief: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Run quality checks and apply safe fixes.

    Returns: (brief, warnings)
    """

    warnings: List[str] = []
    if not isinstance(brief, dict):
        return brief, ["brief: not a dict"]

    # --- Clean top_districts microhood schema ---
    districts = brief.get("top_districts")
    if isinstance(districts, list):
        # Track microhood -> communes to catch duplicates across communes
        mh_to_communes: Dict[str, List[str]] = {}

        for d in districts:
            if not isinstance(d, dict):
                continue
            commune = _norm_dashes(str(d.get("name") or d.get("commune") or "")).strip()
            # Remove legacy keys
            for legacy in ("micro_anchors", "anchors"):
                if legacy in d:
                    d.pop(legacy, None)

            mhs = d.get("microhoods")
            if not isinstance(mhs, list):
                continue

            fixed_mhs: List[Dict[str, Any]] = []
            seen_local = set()
            for mh in mhs:
                if not isinstance(mh, dict):
                    continue
                # Remove legacy key
                if "anchors" in mh:
                    mh.pop("anchors", None)

                nm = _norm_dashes(str(mh.get("name") or ""))
                nm = _strip_near_prefix(nm)
                if not nm:
                    warnings.append(f"microhood: empty name in commune '{commune or '—'}'")
                    continue
                key = nm.casefold()
                if key in seen_local:
                    warnings.append(f"microhood: duplicate '{nm}' inside commune '{commune or '—'}'")
                    continue
                seen_local.add(key)

                # Keywords
                kws = mh.get("portal_keywords") or mh.get("keywords") or []
                if isinstance(kws, str):
                    kws = [kws]
                if not isinstance(kws, list):
                    kws = []
                kws = [_strip_near_prefix(_norm_dashes(str(x))) for x in kws]
                kws = _dedupe_ci([x for x in kws if x])[:4]
                if not kws:
                    kws = _dedupe_ci([nm, "Brussels"])[:4]
                mh["portal_keywords"] = kws
                mh.pop("keywords", None)

                # Highlights (2–3 sentences). Prefer provided highlights; fallback to why/watch_out.
                hl = _norm_dashes(str(mh.get("highlights") or ""))
                if not hl:
                    why = _norm_dashes(str(mh.get("why") or ""))
                    watch = _norm_dashes(str(mh.get("watch_out") or mh.get("risk") or ""))
                    parts = [p for p in [why, watch] if p]
                    hl = " ".join(parts)[:400].strip()
                if not hl:
                    hl = "Good starting point with balanced everyday amenities."
                mh["highlights"] = hl

                # Remove deprecated fields from previous iterations.
                mh.pop("street_hints", None)
                mh.pop("avoid_verify", None)
                mh.pop("avoid", None)
                mh.pop("verify", None)

                fixed_mhs.append({
                    "name": nm,
                    "portal_keywords": mh["portal_keywords"],
                    "highlights": mh["highlights"],
                })

                if commune:
                    mh_to_communes.setdefault(key, []).append(commune)

            d["microhoods"] = fixed_mhs

        # Cross-commune duplicates warning
        for mh_key, comms in mh_to_communes.items():
            uniq = _dedupe_ci(comms)
            if len(uniq) > 1:
                warnings.append(f"microhood: '{mh_key}' appears in multiple communes: {', '.join(uniq)}")

    # Executive summary overflow risk warning
    exec_sum = brief.get("executive_summary")
    if isinstance(exec_sum, list):
        for row in exec_sum:
            if not isinstance(row, dict):
                continue
            for k in ("best_for", "watch_out"):
                v = row.get(k)
                if isinstance(v, str) and len(v) > 140:
                    warnings.append(f"executive_summary: '{k}' is long ({len(v)} chars) for {row.get('name')}")

    return brief, warnings
