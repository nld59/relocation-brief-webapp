
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Compute OSM-based metrics for each commune/district in a city pack and assign data-driven tags + confidence.

Key features:
- Uses `osm_query` override per-commune (to avoid ambiguous geocoding like "City of Brussels").
- Stores metrics under commune["metrics"] and confidence under commune["tag_confidence"].
- Updates ONLY data-driven tags (from rules) unless --overwrite-all-tags is set.
- CLI options: --rules, --high-pct, --medium-pct, --sleep, --verbose
"""

from __future__ import annotations

import argparse
import json
import time
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import osmnx as ox
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, shape


# -----------------------------
# Rules
# -----------------------------

@dataclass
class TagRule:
    tag: str
    metric: str
    top_pct: int


def load_rules(path: Optional[str]) -> List[TagRule]:
    if not path:
        # Default minimal rules (can be extended via tag_rules.json)
        return [
            TagRule("cafes_brunch", "cafes_density", 30),
            TagRule("nightlife", "bars_density", 20),
            TagRule("restaurants", "restaurants_density", 30),
            TagRule("green_parks", "parks_share", 30),
            TagRule("metro_strong", "metro_density", 30),
            TagRule("tram_strong", "tram_density", 30),
            TagRule("schools_strong", "schools_density", 30),
            TagRule("childcare_strong", "childcare_density", 30),
        ]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = []
    for r in data.get("rules", []):
        rules.append(TagRule(tag=r["tag"], metric=r["metric"], top_pct=int(r["top_pct"])))
    return rules


# -----------------------------
# Geometry helpers
# -----------------------------

def _ensure_polygon(geom):
    """Ensure geometry is Polygon/MultiPolygon (OSMnx can return GeometryCollections)."""
    if geom is None:
        raise ValueError("Empty geometry")
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if not polys:
            raise ValueError("GeometryCollection contains no polygons")
        # dissolve if multiple
        out = polys[0]
        for g in polys[1:]:
            out = out.union(g)
        return out
    # Try union if other type
    try:
        return geom.buffer(0)
    except Exception:
        raise ValueError(f"Unsupported geometry type: {type(geom)}")


def area_km2(poly) -> float:
    """Area in km² for a WGS84 polygon.

    Uses an estimated local UTM CRS (fast, offline). This avoids calling
    any OSMnx helper functions that may change across versions.
    """
    return _area_km2_fast(poly)


def _poly_to_gdf(poly):
    import geopandas as gpd
    return gpd.GeoDataFrame({"geometry": [poly]}, crs="EPSG:4326")


# -----------------------------
# OSM queries
# -----------------------------

def geocode_commune_polygon(commune_name: str, city: str, country: Optional[str] = None, osm_query: Optional[str] = None):
    """Geocode commune boundary polygon. Uses osm_query override if provided."""
    if osm_query:
        query = osm_query
    else:
        parts = [commune_name, city]
        if country:
            parts.append(country)
        query = ", ".join(parts)

    gdf = ox.geocode_to_gdf(query)
    geom = _ensure_polygon(gdf.geometry.iloc[0])
    display = str(gdf.iloc[0].get("display_name", ""))
    # compute area in km2 (fast enough here; used for densities)
    akm2 = _area_km2_fast(geom)
    return geom, display, akm2


def _area_km2_fast(poly) -> float:
    import geopandas as gpd
    g = gpd.GeoSeries([poly], crs="EPSG:4326")
    g_proj = g.to_crs(g.estimate_utm_crs())
    return float(g_proj.area.iloc[0] / 1e6)


def _features_from_polygon(poly, tags: Dict[str, Any]):
    """OSMnx compatibility wrapper.
    Newer OSMnx: features_from_polygon; older: geometries_from_polygon.
    Returns a GeoDataFrame or None.
    """
    if hasattr(ox, "features_from_polygon"):
        return ox.features_from_polygon(poly, tags)
    if hasattr(ox, "geometries_from_polygon"):
        return ox.geometries_from_polygon(poly, tags)
    raise AttributeError("OSMnx has neither features_from_polygon nor geometries_from_polygon")


def count_pois(poly, tags: Dict[str, Any], *, sleep_s: float = 0.0, verbose: bool = False, context: str = "") -> int:
    """Count OSM features inside polygon. Returns 0 on empty or any OSMnx errors.
    This is important because some communes/microhood polygons legitimately return no
    features for a given tag set, and OSMnx may raise on empty.
    """
    if sleep_s and sleep_s > 0:
        import time
        time.sleep(sleep_s)

    try:
        gdf = _features_from_polygon(poly, tags)
        if gdf is None or len(gdf) == 0:
            return 0
        return int(len(gdf))
    except Exception as e:
        if verbose:
            prefix = f"{context}: " if context else ""
            print(f"WARN: {prefix}count_pois empty/error for tags={tags}: {e}")
        return 0


# Backward-compatible alias used in microhood metric code paths
def count_features(poly, tags: Dict[str, Any], *, sleep_s: float = 0.0, verbose: bool = False, context: str = "") -> int:
    return count_pois(poly, tags, sleep_s=sleep_s, verbose=verbose, context=context)


def sum_area_km2_of_features(poly, tags: Dict[str, Any], *, sleep_s: float = 0.0, verbose: bool = False, context: str = "") -> float:
    import geopandas as gpd
    if sleep_s and sleep_s > 0:
        import time
        time.sleep(sleep_s)

    try:
        gdf = _features_from_polygon(poly, tags)
        if gdf is None or len(gdf) == 0:
            return 0.0
        geoms = gdf.geometry
        polys = geoms[geoms.type.isin(["Polygon", "MultiPolygon"])]
        if polys.empty:
            return 0.0
        s = gpd.GeoSeries(polys, crs=getattr(gdf, "crs", None))
        s_proj = s.to_crs(epsg=3857)
        return float(s_proj.area.sum() / 1e6)
    except Exception as e:
        if verbose:
            prefix = f"{context}: " if context else ""
            print(f"WARN: {prefix}sum_area_km2_of_features empty/error for tags={tags}: {e}")
        return 0.0


def parks_area_km2(poly, *, sleep_s: float = 0.0, verbose: bool = False, context: str = "") -> float:
    """Area (km^2) of parks inside polygon.

    This is a thin wrapper around `sum_area_km2_of_features` used in multiple
    code paths (communes + microhoods). Having it centralized prevents
    NameError/regressions when refactoring.
    """
    return sum_area_km2_of_features(
        poly,
        {"leisure": "park"},
        sleep_s=sleep_s,
        verbose=verbose,
        context=context,
    )


def percentile_threshold(values: np.ndarray, top_pct: int) -> float:
    """Return value threshold for being in top_pct (e.g. top 30%)."""
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("inf")
    p = 100.0 - float(top_pct)
    return float(np.percentile(values, p))


def compute_city_metrics(city_pack: Dict[str, Any], country: Optional[str], verbose: bool = False, sleep_s: float = 0.0) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    out = json.loads(json.dumps(city_pack))
    city = out.get("city") or out.get("name") or ""

    communes = out.get("communes", [])
    rows = []
    total = len(communes)

    # Make network calls more robust
    ox.settings.requests_timeout = max(getattr(ox.settings, "requests_timeout", 180), 180)
    ox.settings.timeout = max(getattr(ox.settings, "timeout", 180), 180)

    for i, c in enumerate(communes, start=1):
        name = c.get("name")
        if not name:
            continue

        t0 = time.time()
        print(f"[{i}/{total}] Processing: {name} ...", flush=True)

        try:
            t_geo0 = time.time()
            poly, display_name, akm2 = geocode_commune_polygon(name, city, country, osm_query=c.get("osm_query"))
            t_geo = time.time() - t_geo0
            if verbose:
                print(f"    geocode: {t_geo:.1f}s | area_km2={akm2:.2f} | {display_name}", flush=True)

            # Counts
            cafes = count_pois(poly, {"amenity": "cafe"})
            restaurants = count_pois(poly, {"amenity": "restaurant"})
            bars = count_pois(poly, {"amenity": "bar"})

            schools = count_pois(poly, {"amenity": "school"})
            childcare = count_pois(poly, {"amenity": ["kindergarten", "childcare"]})

            # Transit
            metro = 0
            try:
                metro = count_pois(poly, {"railway": "subway_entrance"}) + count_pois(poly, {"station": "subway"})
            except Exception:
                metro = 0
            tram = count_pois(poly, {"railway": "tram_stop"})
            train = count_pois(poly, {"railway": "station", "station": "train"})

            # Green
            parks_area = sum_area_km2_of_features(poly, {"leisure": "park"})
            # woods omitted for speed/reliability

            # Densities / shares
            denom = akm2 if akm2 > 0 else float("nan")
            cafes_density = cafes / denom
            bars_density = bars / denom
            restaurants_density = restaurants / denom
            schools_density = schools / denom
            childcare_density = childcare / denom

            metro_density = metro / denom
            tram_density = tram / denom
            train_density = train / denom

            parks_share = (parks_area / denom) if denom and np.isfinite(denom) else float("nan")

            rows.append({
                "id": c.get("id", str(name).lower().replace(" ", "_")),
                "name": name,
                "area_km2": float(akm2),
                "cafes_count": int(cafes),
                "restaurants_count": int(restaurants),
                "bars_count": int(bars),
                "schools_count": int(schools),
                "childcare_count": int(childcare),
                "metro_stops": int(metro),
                "tram_stops": int(tram),
                "train_stations": int(train),
                "parks_area_km2": float(parks_area),
                "cafes_density": float(cafes_density),
                "restaurants_density": float(restaurants_density),
                "bars_density": float(bars_density),
                "schools_density": float(schools_density),
                "childcare_density": float(childcare_density),
                "metro_density": float(metro_density),
                "tram_density": float(tram_density),
                "train_density": float(train_density),
                "parks_share": float(parks_share),
            })

            if verbose:
                print(
                    f"    cafes={cafes} bars={bars} restaurants={restaurants} schools={schools} childcare={childcare} "
                    f"metro={metro} tram={tram} train={train} parks_km2={parks_area:.3f}",
                    flush=True,
                )
        except Exception as e:
            print(f"    ERROR: {name}: {e}", flush=True)
            # fail-soft row
            rows.append({
                "id": c.get("id", str(name).lower().replace(" ", "_")),
                "name": name,
                "area_km2": 0.0,
                "cafes_count": 0,
                "restaurants_count": 0,
                "bars_count": 0,
                "schools_count": 0,
                "childcare_count": 0,
                "metro_stops": 0,
                "tram_stops": 0,
                "train_stations": 0,
                "parks_area_km2": 0.0,
                "cafes_density": float("nan"),
                "restaurants_density": float("nan"),
                "bars_density": float("nan"),
                "schools_density": float("nan"),
                "childcare_density": float("nan"),
                "metro_density": float("nan"),
                "tram_density": float("nan"),
                "train_density": float("nan"),
                "parks_share": float("nan"),
            })

        t_total = time.time() - t0
        print(f"    done in {t_total:.1f}s", flush=True)
        if sleep_s and sleep_s > 0:
            time.sleep(float(sleep_s))

    df = pd.DataFrame(rows)
    meta = {"city": city, "country": country, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    return df, meta


def assign_data_driven_tags(
    city_pack: Dict[str, Any],
    df: pd.DataFrame,
    rules: List[TagRule],
    overwrite_all_tags: bool,
    high_pct: int = 15,
    medium_pct: int = 30,
) -> Dict[str, Any]:
    """Assign tags and tag_confidence based on within-city percentiles."""
    out = json.loads(json.dumps(city_pack))

    df_by_id = {str(r["id"]): r for r in df.to_dict(orient="records")}
    df_by_name = {str(r["name"]): r for r in df.to_dict(orient="records")}

    rules_by_tag = {r.tag: r for r in rules}
    data_driven_tags = list(rules_by_tag.keys())

    # thresholds for confidence (per metric)
    def thr(metric: str, top_pct: int) -> float:
        return percentile_threshold(df[metric].to_numpy(dtype=float), top_pct)

    metric_high_thr = {r.metric: thr(r.metric, high_pct) for r in rules}
    metric_med_thr = {r.metric: thr(r.metric, medium_pct) for r in rules}
    metric_tag_thr = {r.metric: thr(r.metric, r.top_pct) for r in rules}

    for c in out.get("communes", []):
        key = str(c.get("id") or c.get("name"))
        row = df_by_id.get(key) or df_by_name.get(c.get("name"))
        if not row:
            continue

        # Metrics stored (for downstream / debugging)
        c["metrics"] = {k: (float(row[k]) if isinstance(row[k], (int, float, np.floating)) and np.isfinite(row[k]) else row[k])
                        for k in row.keys() if k != "name" and k != "id"}
        # keep curated tags
        existing = list(c.get("tags", [])) if isinstance(c.get("tags", []), list) else []
        if overwrite_all_tags:
            kept = []
        else:
            kept = [t for t in existing if t not in data_driven_tags]

        new_tags = []
        conf = {}

        for tag, rule in rules_by_tag.items():
            val = float(row.get(rule.metric, float("nan")))
            if not np.isfinite(val):
                continue
            # eligibility threshold for tag itself
            if val >= metric_tag_thr[rule.metric]:
                new_tags.append(tag)
                # confidence
                if val >= metric_high_thr[rule.metric]:
                    conf[tag] = "high"
                elif val >= metric_med_thr[rule.metric]:
                    conf[tag] = "medium"

        # write back
        c["tags"] = kept + new_tags
        c["tag_confidence"] = conf

    return out


# -----------------------------
# Main
# -----------------------------


# --- Microhoods (Monitoring des Quartiers) helpers ---------------------------------
# Sprint-1 goal: use Monitoring des Quartiers as OFFICIAL microhood catalog (no OSM geocoding),
# then optionally compute the same metrics/tags for those microhood polygons.

def _norm_key(s) -> str:
    """Normalize keys used for matching.

    Some identifiers in the pack can be numeric (e.g. monitoring_id). Accepting
    Any and coercing to str prevents runtime errors like:
    TypeError: normalize() argument 2 must be str, not int
    """
    if s is None:
        return ""
    # Coerce to string early (handles int/float/etc.)
    s = str(s)
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

_BRUSSELS_COMMUNE_ALIASES = {
    "cityofbrussels": ["cityofbrussels", "brussels", "bruxelles", "bruxellesville", "brussel", "brusselstad"],
    "anderlecht": ["anderlecht"],
    "auderghem": ["auderghem", "oudergem"],
    "berchemsainteagathe": ["berchemsainteagathe", "sintagathaberchem", "berchem"],
    "etterbeek": ["etterbeek"],
    "evere": ["evere"],
    "forest": ["forest", "vorst"],
    "ganshoren": ["ganshoren"],
    "ixelles": ["ixelles", "elsene"],
    "jette": ["jette"],
    "koekelberg": ["koekelberg"],
    "molenbeeksaintjean": ["molenbeeksaintjean", "sintjansmolenbeek", "molenbeek"],
    "saintgilles": ["saintgilles", "sintgillis"],
    "saintjossetennoode": ["saintjossetennoode", "sintjoosttennode", "saintjosse", "sintjoost"],
    "schaerbeek": ["schaerbeek", "schaarbeek"],
    "uccle": ["uccle", "ukkel"],
    "watermaelboitsfort": ["watermaelboitsfort", "watermaalbosvoorde", "boitsfort", "bosvoorde"],
    "woluwesaintlambert": ["woluwesaintlambert", "sintlambrechtswoluwe"],
    "woluwesaintpierre": ["woluwesaintpierre", "sintpieterswoluwe"],
}

def _download_text(url: str, timeout_s: int = 60) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "relocation-brief-tagging/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read().decode("utf-8")


def _candidate_monitoring_geojson_paths(pack_path: str) -> list[str]:
    """Return likely local paths for Monitoring des Quartiers GeoJSON."""
    base_dir = os.path.dirname(os.path.abspath(pack_path))
    return [
        os.path.join(base_dir, "monitoring_quartiers_full.geojson"),
        os.path.join(base_dir, "monitoring_quartiers.geojson"),
        os.path.join(base_dir, "monitoring_quarters.geojson"),
        os.path.join(".tools_cache", "monitoring_quartiers.geojson"),
        os.path.join(".tools_cache", "monitoring_quarters.geojson"),
    ]


def _try_load_geojson_file(path: str) -> dict | None:
    try:
        if not path or not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # minimal validation
        feats = data.get("features") if isinstance(data, dict) else None
        if not feats or not isinstance(feats, list):
            return None
        # ensure at least one feature has mdrc + geometry
        ok = False
        for ft in feats[:10]:
            props = ft.get("properties", {}) if isinstance(ft, dict) else {}
            if ("mdrc" in props) and ft.get("geometry"):
                ok = True
                break
        return data if ok else None
    except Exception:
        return None


def _parse_geojson(data: Any) -> Dict[str, Any]:
    """Parse GeoJSON payload.

    Accepts either already-parsed dict or JSON text/bytes.
    Provides a short head snippet in the error to make debugging easier.
    """
    if isinstance(data, dict):
        return data
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", errors="replace")
    if not isinstance(data, str):
        raise TypeError(f"Expected GeoJSON str/dict, got {type(data)}")

    s = data.lstrip("\ufeff").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        head = s[:500]
        raise ValueError(f"Invalid GeoJSON payload: {e}. Head: {head!r}") from e


def load_monitoring_quarters_geojson(cache_path: str = ".tools_cache/monitoring_quarters.geojson", verbose: bool = False) -> Dict[str, Any]:
    """Load Monitoring des Quartiers GeoJSON.

    Sprint-1 offline path: we generate the full GeoJSON from the provided GPKG.
    This loader is intentionally robust: it first tries the cache_path, then a
    few well-known local fallbacks.

    Returns the parsed GeoJSON dict.
    """

    candidates = [
        cache_path,
        os.path.join("city_packs", "monitoring_quartiers_full.geojson"),
        os.path.join("city_packs", "monitoring_quartiers.geojson"),
        "monitoring_quartiers_full.geojson",
        "monitoring_quartiers.geojson",
    ]

    for p in candidates:
        if not p:
            continue
        if os.path.exists(p):
            if verbose:
                print(f"[monitoring] loading geojson: {p}")
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _parse_geojson(data)

    raise FileNotFoundError(
        "Monitoring quarters GeoJSON not found. "
        "Run tools/microhoods/build_monitoring_microhoods.py first, "
        "or provide a valid --current-partial-geojson/--out-full-geojson. "
        f"Tried: {', '.join([c for c in candidates if c])}"
    )
def _pick_prop(props: Dict[str, Any], keys: List[str]) -> Optional[str]:
    for k in keys:
        v = props.get(k)
        if v is not None and str(v).strip():
            return str(v)
    return None

def parse_monitoring_quarters(geojson_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    feats = geojson_obj.get("features") or []
    out: List[Dict[str, Any]] = []
    for f in feats:
        props = f.get("properties") or {}
        geom = f.get("geometry")

        commune = _pick_prop(props, ["commune", "commune_fr", "commune_nl", "municipality", "gemeente"])
        if not commune:
            for k in props.keys():
                lk = k.lower()
                if "commune" in lk or "gemeente" in lk or "municip" in lk:
                    commune = str(props.get(k, "")).strip()
                    break

        name = _pick_prop(props, ["name_en","nom_en","quartier_en","wijk_en","quartier","wijk","name","nom","name_fr","nom_fr","name_nl","nom_nl"])
        if not name:
            for k in props.keys():
                lk = k.lower()
                if any(x in lk for x in ["quartier","wijk","name","nom"]):
                    v = props.get(k)
                    if v:
                        name = str(v).strip()
                        break

        mid = _pick_prop(props, ["mdrc","MDRC","id","recordid","code","quartier_id","wijk_id","id_quartier","id_wijk"])
        if not mid:
            mid = f"{_norm_key(commune)}::{_norm_key(name)}"

        out.append({
            "monitoring_id": str(mid),
            "commune_raw": commune or "",
            "name": name or "",
            "geometry": geom,
        })
    return out

def map_microhoods_to_communes(city_pack: Dict[str, Any], microhoods: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    communes = city_pack.get("communes", [])
    alias_to_commune: Dict[str, str] = {}
    for c in communes:
        cname = c.get("name") or ""
        key = _norm_key(cname)
        aliases = _BRUSSELS_COMMUNE_ALIASES.get(key, [key])
        for a in aliases:
            alias_to_commune[_norm_key(a)] = cname

    out: Dict[str, List[Dict[str, Any]]] = { (c.get("name") or ""): [] for c in communes }
    for mh in microhoods:
        ck = _norm_key(mh.get("commune_raw",""))
        cname = alias_to_commune.get(ck)
        if not cname:
            for ak, canon in alias_to_commune.items():
                if ak and (ak in ck or ck in ak):
                    cname = canon
                    break
        if cname and cname in out:
            out[cname].append(mh)
    return out

def ensure_microhoods_in_pack(
    city_pack: Dict[str, Any],
    min_per_commune: int = 8,
    max_per_commune: int = 12,
    cache_path: str = ".tools_cache/monitoring_quarters.geojson",
    verbose: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    geo = load_monitoring_quarters_geojson(cache_path=cache_path, verbose=verbose)
    microhoods = parse_monitoring_quarters(geo)
    by_commune = map_microhoods_to_communes(city_pack, microhoods)

    geom_by_id: Dict[str, Any] = {}
    area_km2_by_id: Dict[str, float] = {}
    for mh in microhoods:
        mid = mh["monitoring_id"]
        geom = mh.get("geometry")
        if geom:
            geom_by_id[mid] = geom
            try:
                poly = shape(geom)
                poly_proj, _ = ox.projection.project_geometry(poly)
                area_km2_by_id[mid] = float(poly_proj.area) / 1e6
            except Exception:
                area_km2_by_id[mid] = 0.0
        else:
            area_km2_by_id[mid] = 0.0

    out = json.loads(json.dumps(city_pack))
    for c in out.get("communes", []):
        cname = c.get("name") or ""
        existing = c.get("microhoods") or []
        existing_ids = {_norm_key(str(x.get("monitoring_id", x.get("id","")))) for x in existing if isinstance(x, dict)}
        candidates = sorted(by_commune.get(cname, []), key=lambda x: area_km2_by_id.get(x["monitoring_id"], 0.0), reverse=True)

        picked = []
        for mh in candidates:
            mid = mh["monitoring_id"]
            if _norm_key(mid) in existing_ids:
                continue
            if not mh.get("name"):
                continue
            picked.append({"name": mh["name"], "monitoring_id": str(mid), "id": int(str(mid)) if str(mid).isdigit() else str(mid), "source": "monitoring_des_quartiers"})
            if len(picked) >= max_per_commune:
                break

        merged = list(existing) + picked
        merged = sorted(merged, key=lambda x: area_km2_by_id.get(str(x.get("monitoring_id","")), 0.0), reverse=True)[:max_per_commune]
        # Ensure minimum: if after dedupe we got less than min, keep as-is (communes differ), but log
        c["microhoods"] = merged
        if verbose and len(merged) < min_per_commune:
            print(f"WARN {cname}: only {len(merged)} microhoods mapped from Monitoring dataset")

    monitoring_index = {"geometry_by_id": geom_by_id, "area_km2_by_id": area_km2_by_id, "cache_path": cache_path}
    return out, monitoring_index

def compute_microhood_metrics(city_pack: Dict[str, Any], monitoring_index: Dict[str, Any], verbose: bool = False, sleep_s: float = 0.0) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    out = json.loads(json.dumps(city_pack))
    geom_by_id = monitoring_index.get("geometry_by_id", {})
    area_by_id = monitoring_index.get("area_km2_by_id", {})

    rows = []
    communes = out.get("communes", [])
    for ci, c in enumerate(communes, start=1):
        cname = c.get("name") or ""
        microhoods = c.get("microhoods") or []
        if not microhoods:
            continue
        if verbose:
            print(f"--- {cname}: microhoods ({len(microhoods)}) [{ci}/{len(communes)}] ---")

        for mh in microhoods:
            mid = str(mh.get("monitoring_id", mh.get("id","")))
            mname = str(mh.get("name","")).strip()
            geom = geom_by_id.get(mid)
            if not geom:
                if verbose:
                    print(f"ERROR {mname}: missing geometry for monitoring_id={mid}")
                continue
            try:
                poly = shape(geom)
            except Exception as e:
                if verbose:
                    print(f"ERROR {mname}: invalid geometry: {e}")
                continue

            try:
                area_km2 = float(area_by_id.get(mid, 0.0))
                cafes = count_features(poly, {"amenity": "cafe"}, sleep_s=sleep_s)
                bars = count_features(poly, {"amenity": ["bar", "pub", "nightclub"]}, sleep_s=sleep_s)
                restaurants = count_features(poly, {"amenity": "restaurant"}, sleep_s=sleep_s)
                schools = count_features(poly, {"amenity": ["school", "kindergarten"]}, sleep_s=sleep_s)
                childcare = count_features(poly, {"amenity": ["childcare"]}, sleep_s=sleep_s)
                metro = count_features(poly, {"railway": "station", "station": "subway"}, sleep_s=sleep_s)
                tram = count_features(poly, {"railway": "tram_stop"}, sleep_s=sleep_s)
                train = count_features(poly, {"railway": "station"}, sleep_s=sleep_s)
                parks_km2 = parks_area_km2(poly, sleep_s=sleep_s)
            except Exception as e:
                if verbose:
                    print(f"ERROR {mname}: {e}")
                continue

            def _safe_div(a,b):
                return a/b if b else 0.0

            metrics = {
                "area_km2": area_km2,
                "cafes": cafes,
                "bars": bars,
                "restaurants": restaurants,
                "schools": schools,
                "childcare": childcare,
                "metro": metro,
                "tram": tram,
                "train": train,
                "parks_km2": parks_km2,
                "cafes_density": _safe_div(cafes, area_km2),
                "bars_density": _safe_div(bars, area_km2),
                "restaurant_density": _safe_div(restaurants, area_km2),
                "schools_density": _safe_div(schools, area_km2),
                "childcare_density": _safe_div(childcare, area_km2),
                "metro_station_density": _safe_div(metro, area_km2),
                "tram_stop_density": _safe_div(tram, area_km2),
                "train_station_density": _safe_div(train, area_km2),
                "parks_share": _safe_div(parks_km2, area_km2),
            }
            mh["metrics"] = metrics

            rows.append({
                "commune": cname,
                "monitoring_id": mid,
                "microhood": mname,
                **{k: metrics[k] for k in [
                    "cafes_density","bars_density","restaurant_density","parks_share",
                    "metro_station_density","tram_stop_density","train_station_density",
                    "schools_density","childcare_density"
                ]}
            })

    return pd.DataFrame(rows), out

def assign_tags_to_microhoods(city_pack: Dict[str, Any], df_micro: pd.DataFrame, rules: List[TagRule], high_pct: int, medium_pct: int) -> Dict[str, Any]:
    out = json.loads(json.dumps(city_pack))
    if df_micro is None or df_micro.empty:
        return out

    for c in out.get("communes", []):
        cname = c.get("name") or ""
        microhoods = c.get("microhoods") or []
        sub = df_micro[df_micro["commune"] == cname]
        if sub.empty:
            continue

        # Precompute percentile ranks per metric within commune (1.0 = best)
        pct_rank = {}
        for r in rules:
            metric = r.metric
            if metric in sub.columns:
                pct_rank[metric] = sub[metric].astype(float).rank(pct=True, method="max")

        for mh in microhoods:
            mid = str(mh.get("monitoring_id",""))
            row = sub[sub["monitoring_id"] == mid]
            if row.empty:
                continue
            idx = row.index[0]
            mh["tag_confidence"] = {}
            for r in rules:
                metric = r.metric
                if metric not in pct_rank:
                    continue
                pct = float(pct_rank[metric].loc[idx])  # higher is better
                # Tag rule uses "top_pct": we interpret as best (1-top_pct .. 1]
                if pct < (1.0 - float(r.top_pct)):
                    continue
                conf = None
                if pct >= (1.0 - high_pct/100.0):
                    conf = "high"
                elif pct >= (1.0 - medium_pct/100.0):
                    conf = "medium"
                if conf:
                    mh["tag_confidence"][r.tag] = conf
    return out

# ----------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    # NOTE: Backward-compatible CLI aliases (older scripts used --pack/--out-pack)
    ap.add_argument("--city-pack", dest="city_pack", help="Path to city pack JSON (e.g. city_packs/brussels.json). Alias: --pack")
    ap.add_argument("--pack", dest="city_pack", help=argparse.SUPPRESS)
    ap.add_argument("--country", default=None, help="Country name (e.g. Belgium)")
    ap.add_argument("--out", dest="out", help="Output path (can be same as input). Alias: --out-pack")
    ap.add_argument("--out-pack", dest="out", help=argparse.SUPPRESS)
    ap.add_argument("--rules", default=None, help="Path to tag_rules.json (optional)")
    ap.add_argument("--overwrite-all-tags", action="store_true", help="Overwrite ALL tags (dangerous). Default keeps curated tags.")
    ap.add_argument("--high-pct", type=int, default=15, help="Confidence=high threshold: top X%% within city (default 15)")
    ap.add_argument("--medium-pct", type=int, default=30, help="Confidence=medium threshold: top X%% within city (default 30)")
    ap.add_argument("--verbose", action="store_true", help="Print per-commune progress and key numbers")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep between communes to avoid rate limiting")
    ap.add_argument("--ensure-microhoods", action="store_true", help="Attach Monitoring des Quartiers microhood catalog into the city pack (8–12 per commune)")
    ap.add_argument("--include-microhoods", action="store_true", help="Compute metrics + tags for microhoods as well (uses Monitoring polygons + OSM)")
    ap.add_argument("--microhoods-min", type=int, default=8, help="Minimum microhoods per commune (default: 8)")
    ap.add_argument("--microhoods-max", type=int, default=12, help="Maximum microhoods per commune (default: 12)")
    args = ap.parse_args()

    # Validate required paths after parsing so aliases are supported.
    if not getattr(args, "city_pack", None):
        ap.error("missing required argument: --city-pack (or --pack)")
    if not getattr(args, "out", None):
        ap.error("missing required argument: --out (or --out-pack)")


    pack_path = Path(args.city_pack)
    pack = json.loads(pack_path.read_text(encoding="utf-8"))

    monitoring_index = None
    if args.ensure_microhoods or args.include_microhoods:
        pack, monitoring_index = ensure_microhoods_in_pack(
            pack,
            min_per_commune=args.microhoods_min,
            max_per_commune=args.microhoods_max,
            verbose=args.verbose,
        )

    rules = load_rules(args.rules)

    df, meta = compute_city_metrics(pack, args.country, verbose=args.verbose, sleep_s=args.sleep)

    # Save CSV next to output
    out_path = Path(args.out)
    csv_path = out_path.with_suffix("").with_name(out_path.stem + "_metrics.csv")
    df.to_csv(csv_path, index=False)

    updated = assign_data_driven_tags(
        pack,
        df,
        rules,
        overwrite_all_tags=args.overwrite_all_tags,
        high_pct=int(args.high_pct),
        medium_pct=int(args.medium_pct),
    )
    updated["_metrics_meta"] = meta


    if args.include_microhoods:
        if monitoring_index is None:
            raise RuntimeError("include-microhoods requires Monitoring index (run with --ensure-microhoods).")
        df_micro, updated = compute_microhood_metrics(updated, monitoring_index, verbose=args.verbose, sleep_s=args.sleep)
        updated = assign_tags_to_microhoods(updated, df_micro, rules, high_pct=args.high_pct, medium_pct=args.medium_pct)
        # Save microhood CSV next to output
        mh_csv = out_path.with_suffix("").with_name(out_path.stem + "_microhoods_metrics.csv")
        if not df_micro.empty:
            df_micro.to_csv(mh_csv, index=False)

    out_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ Saved: {out_path}", flush=True)
    print(f"✅ Metrics CSV: {csv_path}", flush=True)


if __name__ == "__main__":
    main()