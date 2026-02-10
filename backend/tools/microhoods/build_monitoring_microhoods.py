#!/usr/bin/env python3
"""Offline builder for Brussels "Monitoring des Quartiers" microhoods.

Inputs:
- An Excel table mapping Commune_EN -> Microquarter_EN
- A GeoPackage (GPKG) containing 145 monitoring quarters with geometry + names

Outputs:
- Full GeoJSON FeatureCollection (all quarters)
- Missing GeoJSON (if any mappings are missing)
- Updated city pack JSON with microhoods_all + microhoods per commune
- Also writes a cache file to .tools_cache/monitoring_quarters.geojson for compute_metrics_and_tags.py

This script intentionally avoids any network calls."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from shapely.geometry import shape, mapping as geom_mapping
from shapely.ops import transform as shp_transform
from pyproj import Transformer


# ----------------------------
# Helpers
# ----------------------------

def _norm(s: str, keep_hyphen: bool = True) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("’", "'").replace("–", "-").replace("—", "-")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    if keep_hyphen:
        s = re.sub(r"[^\w\s-]", " ", s)
    else:
        s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _display_name(raw: str) -> str:
    s = str(raw or "").strip()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s+", " ", s).strip()

    def fix_word(w: str) -> str:
        if not w:
            return w
        if w.isupper() and len(w) <= 4:
            return w
        low = w.lower()
        if low in {"de", "du", "des", "la", "le", "les", "aux", "au", "d", "l", "et"}:
            return low
        if low.startswith("d'") or low.startswith("l'"):
            return low[:2] + low[2:].capitalize()
        return w.capitalize()

    out: List[str] = []
    for token in s.split(" "):
        if token == "-":
            out.append("-")
            continue
        parts = token.split("'")
        if len(parts) > 1:
            out.append("'".join([fix_word(parts[0])] + [p.capitalize() for p in parts[1:]]))
        else:
            out.append(fix_word(token))
    return " ".join(out)


@dataclass
class Quarter:
    mdrc: int
    name_fr: str
    name_nl: str
    name_bil: str
    geom: Any  # shapely geometry (EPSG:4326)


def _gpkg_geom_to_wkb(gpkg_blob: bytes) -> bytes:
    """
    Extract WKB geometry payload from a GeoPackage geometry BLOB.
    """
    if gpkg_blob is None:
        return None
    if len(gpkg_blob) < 8 or gpkg_blob[0:2] != b"GP":
        raise ValueError("not a valid GeoPackage geometry blob")
    flags = gpkg_blob[3]
    little_endian = (flags & 0b00000001) == 1
    envelope_indicator = (flags >> 1) & 0b00000111  # bits 1-3
    offset = 8
    env_size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope_indicator, 0)
    offset += env_size
    return gpkg_blob[offset:]


def _read_gpkg(gpkg_path: str) -> tuple[dict, dict]:
    """
    Read a .gpkg without requiring fiona/geopandas.
    Returns: (geojson_feature_collection, meta)
    """
    from shapely import wkb as _shapely_wkb

    con = sqlite3.connect(gpkg_path)
    cur = con.cursor()

    layers = [r[0] for r in cur.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features' ORDER BY table_name"
    ).fetchall()]

    if not layers:
        raise RuntimeError("No feature layers found in GeoPackage (gpkg_contents empty).")

    layer = "urbadm_md" if "urbadm_md" in layers else layers[0]

    geom_row = cur.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
        (layer,),
    ).fetchone()
    geom_col = geom_row[0] if geom_row else "geom"

    cols_info = cur.execute(f"PRAGMA table_info({layer})").fetchall()
    cols = [r[1] for r in cols_info]

    if geom_col not in cols:
        blob_cols = [r[1] for r in cols_info if (r[2] or "").upper().find("BLOB") >= 0]
        if blob_cols:
            geom_col = blob_cols[0]
        else:
            raise RuntimeError(f"Geometry column not found for layer '{layer}'.")

    geom_idx = cols.index(geom_col)

    cur.execute(f"SELECT {', '.join(cols)} FROM {layer}")
    features: list[dict] = []
    while True:
        batch = cur.fetchmany(500)
        if not batch:
            break
        for row in batch:
            geom_blob = row[geom_idx]
            geom_json = None
            if geom_blob is not None:
                try:
                    wkb_bytes = _gpkg_geom_to_wkb(geom_blob)
                    geom = _shapely_wkb.loads(wkb_bytes) if wkb_bytes else None
                    geom_json = geom.__geo_interface__ if geom is not None else None
                except Exception:
                    geom_json = None

            props = {c: v for c, v in zip(cols, row) if c != geom_col}
            features.append({"type": "Feature", "geometry": geom_json, "properties": props})

    con.close()

    fc = {"type": "FeatureCollection", "features": features}
    meta = {"available_layers": layers, "selected_layer": layer, "geom_col": geom_col, "count": len(features)}
    return fc, meta

def _quarters_from_geojson(fc: Dict[str, Any]) -> List[Quarter]:
    """Convert a GeoJSON FeatureCollection into canonical Quarter objects."""
    quarters: List[Quarter] = []
    for feat in (fc or {}).get("features", []):
        props = (feat or {}).get("properties") or {}
        geom_dict = (feat or {}).get("geometry")
        try:
            geom = shape(geom_dict) if geom_dict else None
        except Exception:
            geom = None

        def _p(*keys: str) -> Any:
            for k in keys:
                if k in props and props[k] not in (None, ""):
                    return props[k]
            return None

        mdrc = _p("mdrc", "MDRC")
        if mdrc is None:
            # skip malformed features
            continue

        name_fr = _p("name_fr", "NAME_FR", "nameFR", "NAMEFR") or ""
        name_nl = _p("name_nl", "NAME_NL", "nameNL", "NAMENL") or ""
        name_bil = _p("name_bil", "NAME_BIL", "name_bilingual", "NAME_BILINGUAL") or ""
        if not name_bil:
            # reasonable fallback: bilingual = FR (most common in Brussels datasets)
            name_bil = str(name_fr) if name_fr else str(name_nl)

        quarters.append(
            Quarter(
                mdrc=int(mdrc),
                name_fr=str(name_fr),
                name_nl=str(name_nl),
                name_bil=str(name_bil),
                geom=geom,
            )
        )
    return quarters

def _build_alias_index(quarters: Iterable[Quarter]) -> Dict[str, List[int]]:
    idx: Dict[str, List[int]] = defaultdict(list)
    for q in quarters:
        aliases = {str(q.mdrc), q.name_bil, q.name_fr, q.name_nl}
        # bilingual splits
        for part in re.split(r"\s*/\s*", q.name_bil):
            if part:
                aliases.add(part)
        for a in aliases:
            for keep in (True, False):
                key = _norm(a, keep_hyphen=keep)
                if key:
                    idx[key].append(q.mdrc)
    return idx


def _match_quarter_id(name: str, alias_idx: Dict[str, List[int]], quarters_by_id: Dict[int, Quarter]) -> Optional[int]:
    # 1) exact match (with/without hyphen)
    for keep in (True, False):
        key = _norm(name, keep_hyphen=keep)
        hits = alias_idx.get(key) or []
        if hits:
            return hits[0]  # deterministic
    # 2) prefix match (handles truncated Excel cells)
    key = _norm(name, keep_hyphen=False)
    if len(key) >= 6:
        for qid, q in quarters_by_id.items():
            for cand in (q.name_fr, q.name_nl, q.name_bil):
                if _norm(cand, keep_hyphen=False).startswith(key):
                    return qid
    # 3) fuzzy fallback (last resort)
    try:
        import difflib
        cand_norm = [(_norm(q.name_fr, False), q.mdrc) for q in quarters_by_id.values() if q.name_fr]
        cand_norm.sort(key=lambda x: x[0])
        names = [c[0] for c in cand_norm]
        close = difflib.get_close_matches(key, names, n=1, cutoff=0.60)
        if close:
            idx = names.index(close[0])
            return cand_norm[idx][1]
    except Exception:
        pass
    return None


def _area_km2_and_centroid(geom) -> Tuple[float, float, float]:
    # compute area in EPSG:3857 (good enough for ranking/selection)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    proj = transformer.transform
    g2 = shp_transform(proj, geom)
    area_km2 = float(g2.area) / 1e6
    c = geom.centroid
    return area_km2, float(c.x), float(c.y)


def _select_spread(quarter_ids: List[int], meta: Dict[int, Dict[str, float]], n_max: int) -> List[int]:
    if len(quarter_ids) <= n_max:
        return quarter_ids[:]
    # sort by area desc
    q_sorted = sorted(quarter_ids, key=lambda qid: meta[qid]["area_km2"], reverse=True)
    selected = [q_sorted[0]]
    remaining = set(q_sorted[1:])

    def dist2(a: int, b: int) -> float:
        ax, ay = meta[a]["lon"], meta[a]["lat"]
        bx, by = meta[b]["lon"], meta[b]["lat"]
        return (ax - bx) ** 2 + (ay - by) ** 2

    while len(selected) < n_max and remaining:
        best = None
        best_score = -1.0
        for cand in list(remaining):
            mind = min(dist2(cand, s) for s in selected)
            score = mind * (1.0 + 0.05 * meta[cand]["area_km2"])
            if score > best_score:
                best_score = score
                best = cand
        selected.append(best)
        remaining.remove(best)
    return selected


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Build Monitoring microhoods for Brussels offline (GPKG + Excel).")
    ap.add_argument("--pack", required=True, help="Path to city pack JSON (e.g., city_packs/brussels.json)")
    ap.add_argument("--out-pack", required=True, help="Where to write updated pack JSON")
    ap.add_argument("--excel", default="city_packs/brussels_communes_microquarters.xlsx",
                    help="Excel mapping Commune_EN -> Microquarter_EN")
    ap.add_argument("--gpkg", default="city_packs/urbadm_md.gpkg",
                    help="GeoPackage with monitoring quarters (145 features)")
    ap.add_argument("--out-full-geojson", default="city_packs/monitoring_quartiers_full.geojson",
                    help="Where to write full quarters GeoJSON")
    ap.add_argument("--out-missing-geojson", default="city_packs/monitoring_quartiers_missing.geojson",
                    help="Where to write missing mapping GeoJSON")
    ap.add_argument("--cache-geojson", default=".tools_cache/monitoring_quarters.geojson",
                    help="Cache path used by compute_metrics_and_tags.py")
    ap.add_argument("--n-min", type=int, default=8)
    ap.add_argument("--n-max", type=int, default=12)
    ap.add_argument("--verbose", action="store_true")

    # Keep legacy args for compatibility (ignored)
    ap.add_argument("--current-partial-geojson", default=None)
    ap.add_argument("--page-size", type=int, default=500)
    ap.add_argument("--timeout", type=int, default=60)

    args = ap.parse_args()
    verbose = bool(args.verbose)

    if not os.path.exists(args.excel):
        raise FileNotFoundError(
            f"Excel mapping not found: {args.excel}. "
            "Put brussels_communes_microquarters.xlsx into city_packs/ or pass --excel PATH."
        )
    if not os.path.exists(args.gpkg):
        raise FileNotFoundError(
            f"GPKG not found: {args.gpkg}. "
            "Put urbadm_md.gpkg into city_packs/ or pass --gpkg PATH."
        )

    # Load pack
    with open(args.pack, "r", encoding="utf-8") as f:
        pack = json.load(f)

    communes = pack.get("communes") or []
    commune_names = [c.get("name") for c in communes if c.get("name")]

    # Load inputs
    full_geojson, _meta = _read_gpkg(args.gpkg)
    quarters = _quarters_from_geojson(full_geojson)

    quarters_by_id = {q.mdrc: q for q in quarters if q.mdrc}

    alias_idx = _build_alias_index(quarters)

    df = pd.read_excel(args.excel)
    required_cols = {"Commune_EN", "Microquarter_EN"}
    if not required_cols.issubset(set(df.columns)):
        raise RuntimeError(f"Excel must contain columns {sorted(required_cols)}. Found: {list(df.columns)}")

    # Map mdrc -> commune + best display name
    rows: List[Tuple[int, str, str]] = []
    errors: List[str] = []
    for i, row in df.iterrows():
        comm = str(row["Commune_EN"]).strip()
        mq = str(row["Microquarter_EN"]).strip()
        if not comm or not mq:
            continue
        qid = _match_quarter_id(mq, alias_idx, quarters_by_id)
        if qid is None:
            errors.append(f"Unmatched microquarter in Excel: '{mq}' (commune='{comm}')")
            continue
        rows.append((qid, comm, mq))

    if errors:
        msg = "\n".join(errors[:20])
        raise RuntimeError(f"Could not match some Excel rows to GPKG quarters:\n{msg}")

    # Build mapping from Excel: quarter id -> communes (can belong to multiple communes)
    qid_to_communes: Dict[int, List[str]] = defaultdict(list)
    commune_to_ids: Dict[str, List[int]] = defaultdict(list)
    for qid, comm, mq in rows:
        if comm:
            qid_to_communes[qid].append(comm)
            commune_to_ids[comm].append(qid)

    # Deduplicate while preserving order
    for comm, ids in list(commune_to_ids.items()):
        seen = set()
        dedup = []
        for qid in ids:
            if qid in seen:
                continue
            seen.add(qid)
            dedup.append(qid)
        commune_to_ids[comm] = dedup

    for qid, comms in list(qid_to_communes.items()):
        # Unique, stable order
        seen=set()
        out=[]
        for c in comms:
            if c in seen: 
                continue
            seen.add(c)
            out.append(c)
        qid_to_communes[qid]=out

    # For convenience we keep a primary commune (most frequent in Excel) for GeoJSON properties only
    qid_to_primary_comm: Dict[int, str] = {}
    for qid, comms in qid_to_communes.items():
        if not comms:
            continue
        # most frequent based on original rows order/count
        counts = defaultdict(int)
        for _qid, _comm, _mq in rows:
            if _qid == qid:
                counts[_comm] += 1
        qid_to_primary_comm[qid] = max(counts.keys(), key=lambda k: counts[k])

    # Determine best display name for each quarter id (longest string from Excel rows)
    qid_to_name: Dict[int, str] = {}
    tmpn = defaultdict(list)
    for qid, comm, mq in rows:
        tmpn[qid].append(mq)
    for qid, names in tmpn.items():
        qid_to_name[qid] = max(names, key=lambda s: len(str(s)))

    # Build GeoJSON
    features: List[Dict[str, Any]] = []
    meta: Dict[int, Dict[str, float]] = {}
    missing_features: List[Dict[str, Any]] = []
    for q in quarters:
        area_km2, lon, lat = _area_km2_and_centroid(q.geom)
        meta[q.mdrc] = {"area_km2": area_km2, "lon": lon, "lat": lat}
        comm = qid_to_primary_comm.get(q.mdrc)
        props = {
            "mdrc": q.mdrc,
            "commune_en": comm,
            "communes_en": qid_to_communes.get(q.mdrc, []),
            "name_fr": q.name_fr,
            "name_nl": q.name_nl,
            "name_bil": q.name_bil,
            "area_km2": area_km2,
            "centroid_lon": lon,
            "centroid_lat": lat,
        }
        feat = {"type": "Feature", "properties": props, "geometry": geom_mapping(q.geom)}
        features.append(feat)
        if comm is None:
            missing_features.append(feat)

    full_geo = {"type": "FeatureCollection", "features": features}
    os.makedirs(os.path.dirname(args.out_full_geojson) or ".", exist_ok=True)
    with open(args.out_full_geojson, "w", encoding="utf-8") as f:
        json.dump(full_geo, f, ensure_ascii=False)
    if verbose:
        print(f"[write] full geojson: {args.out_full_geojson} (features={len(features)})")

    missing_geo = {"type": "FeatureCollection", "features": missing_features}
    os.makedirs(os.path.dirname(args.out_missing_geojson) or ".", exist_ok=True)
    with open(args.out_missing_geojson, "w", encoding="utf-8") as f:
        json.dump(missing_geo, f, ensure_ascii=False)
    if verbose:
        print(f"[write] missing geojson: {args.out_missing_geojson} (features={len(missing_features)})")

    # Also write cache for compute_metrics_and_tags.py
    os.makedirs(os.path.dirname(args.cache_geojson) or ".", exist_ok=True)
    with open(args.cache_geojson, "w", encoding="utf-8") as f:
        json.dump(full_geo, f, ensure_ascii=False)
    if verbose:
        print(f"[write] cache geojson: {args.cache_geojson}")


    # Build a canonical microhood catalog (unique polygons, 145) keyed by monitoring_id.
    # This is the "source of truth" for metrics/profiles; communes may reference the same id multiple times.
    microhood_catalog = []
    for q in quarters:
        qid = int(q.mdrc)
        display = _display_name(qid_to_name.get(qid, q.name_fr))
        microhood_catalog.append({
            "id": qid,
            "monitoring_id": qid,
            "name": display,
            "communes_en": qid_to_communes.get(qid, []),
            "meta": meta.get(qid, {}),
            "source": "urbadm_md.gpkg + brussels_communes_microquarters.xlsx",
        })
    pack["microhood_catalog"] = sorted(microhood_catalog, key=lambda x: int(x.get("id", 0)))

    # Update pack communes: microhoods_all + microhoods selection
    # commune_to_ids already computed from Excel (supports many-to-many)
# Validate commune names
    unknown = sorted(set(commune_to_ids.keys()) - set(commune_names))
    if unknown:
        raise RuntimeError(
            "Excel contains commune names that are not present in pack:\n"
            + "\n".join(unknown)
        )

    for c in communes:
        comm = c.get("name")
        if not comm:
            continue
        qids = sorted(commune_to_ids.get(comm, []))
        micro_all = [{"id": int(qid), "monitoring_id": int(qid), "name": _display_name(qid_to_name.get(qid, quarters_by_id[qid].name_fr))} for qid in qids]
        c["microhoods_all"] = micro_all

        # select between n_min/n_max (we choose up to n_max if available)
        n_max = max(1, int(args.n_max))
        sel_ids = _select_spread(qids, meta, n_max=n_max) if qids else []
        micro_sel = [{"id": int(qid), "monitoring_id": int(qid), "name": _display_name(qid_to_name.get(qid, quarters_by_id[qid].name_fr))} for qid in sel_ids]
        c["microhoods"] = micro_sel
        c["microhoods_source"] = "urbadm_md.gpkg + brussels_communes_microquarters.xlsx"

        if verbose:
            print(f"[pack] {comm}: microhoods_all={len(micro_all)} selected={len(micro_sel)}")

    pack["communes"] = communes
    os.makedirs(os.path.dirname(args.out_pack) or ".", exist_ok=True)
    with open(args.out_pack, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"[write] updated pack: {args.out_pack}")


if __name__ == "__main__":
    main()
