from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional

def load_city_pack(city: str) -> Optional[Dict[str, Any]]:
    if not city:
        return None
    key = city.strip().lower()
    aliases = {"bruxelles":"brussels","brussel":"brussels","brussels":"brussels"}
    key = aliases.get(key, key)
    pack_path = Path(__file__).resolve().parent.parent / "city_packs" / f"{key}.json"
    if not pack_path.exists():
        return None
    try:
        return json.loads(pack_path.read_text(encoding="utf-8"))
    except Exception:
        return None
