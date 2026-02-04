from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


def _normalize_city_key(city: str) -> str:
    """Normalize user/UI city strings into a stable city-pack key.

    The UI might send values like:
      - "Brussels"
      - "Brussels, Belgium"
      - "Belgium/Brussels"
      - "Bruxelles" / "Brussel"

    We need this to be resilient, otherwise the city pack won't load and
    the report degrades (empty resources, missing communes, all-5/5 scores).
    """
    s = (city or "").strip().lower()
    if not s:
        return ""

    # Split common composite formats
    parts = re.split(r"[,/|\\-]+", s)
    parts = [p.strip() for p in parts if p and p.strip()]
    # Often "Belgium/Brussels" → pick last, but "Brussels, Belgium" → pick first.
    countries = {
        "belgium", "be", "spain", "es", "france", "fr", "italy", "it", "germany", "de",
        "netherlands", "nl", "uk", "united kingdom", "usa", "united states",
    }
    if not parts:
        s0 = s
    elif parts[-1] in countries and len(parts) >= 2:
        s0 = parts[0]
    else:
        s0 = parts[-1]

    aliases = {
        "bruxelles": "brussels",
        "brussel": "brussels",
        "brussels": "brussels",
        "bruxelles (brussels)": "brussels",
    }
    s0 = aliases.get(s0, s0)

    # Remove non-letter leftovers (e.g., "brussels belgium")
    s0 = re.sub(r"\s+", " ", s0).strip()
    return s0


def load_city_pack(city: str) -> Optional[Dict[str, Any]]:
    if not city:
        return None
    key = _normalize_city_key(city)
    if not key:
        return None

    pack_path = Path(__file__).resolve().parent.parent / "city_packs" / f"{key}.json"
    if not pack_path.exists():
        return None
    try:
        return json.loads(pack_path.read_text(encoding="utf-8"))
    except Exception:
        return None
