import json
import re
import os
from pathlib import Path
from typing import Dict, Any
from json import JSONDecodeError

from openai import OpenAI

from .city_packs import load_city_pack


def _load_microhood_commune_map() -> Dict[str, str]:
    """Map microhood name variants -> commune_en using monitoring_quartiers_full.geojson.

    This is used as a validator so the LLM cannot recommend microhoods outside a commune.
    """
    geo_path = Path(__file__).resolve().parent.parent / "city_packs" / "monitoring_quartiers_full.geojson"
    if not geo_path.exists():
        return {}
    try:
        data = json.loads(geo_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    out: Dict[str, str] = {}
    for feat in data.get("features", []) or []:
        props = feat.get("properties") or {}
        commune = str(props.get("commune_en") or "").strip()
        if not commune:
            continue
        for k in ["name_fr", "name_nl", "name_bil"]:
            nm = str(props.get(k) or "").strip()
            if nm:
                out[_norm(nm)] = commune
    return out


SYSTEM_INSTRUCTIONS = """You are a B2B relocation brief assistant.
Return ONLY valid JSON (no markdown, no extra text). Keep it concise and premium.

Style rules (VERY IMPORTANT):
- Be specific; avoid generic filler.
- Bullets must be short and concrete.
- Do NOT output any raw dictionaries or JSON inside text fields.
- client_profile must be plain English (not JSON), concise and premium.

Client profile (VERY IMPORTANT):
- Must be 2–3 short sentences.
- Hard cap: <= 230 characters total.
- Must fit in 3 lines in a PDF card.
- Mention: who + city + mode (buy/rent) + budget + 2–3 priorities.

Typography rules (IMPORTANT):
- Use plain ASCII characters only (no curly quotes/apostrophes).
- Use "15-minute" (hyphen) or "15 min".

Completeness rules (VERY IMPORTANT):
- Never end a sentence/bullet with a dangling word such as:
  "at", "near", "with", "and", "or", "to", "from", "for", "via", "of", "in", "on", "around", "towards".
- Also never end with unfinished location tokens such as:
  "Via", "Rue", "Avenue", "Corso", "Boulevard", "Street", "St.", "Rd.", "east of", "west of", "north of", "south of".
- No truncated phrases. Each bullet must be a complete thought with a clear object.

Limits:
- must_have: max 8 items
- nice_to_have: max 8 items
- red_flags: max 8 items
- contradictions (trade-offs): max 8 items
- next_steps: max 12 items (concrete 1–2 week plan)
- top_districts: exactly 3 districts
  - why: EXACTLY 2 bullets
  - watch_out: EXACTLY 1 bullet
- real_estate_sites: max 3
- agencies: max 5

Top-3 district explanation rules (VERY IMPORTANT):
- District names must be EXACT matches of commune names from the city pack shortlist.
- NEVER use neighborhood/micro-area labels (e.g., "European Quarter", "Sablon") as a district name.
- If you want to mention a micro-area, do it inside why bullets as an anchor or in micro_anchors field.
- Each district "why" must be specific and local (micro-areas, parks, schools, transit).
- Each "why" bullet must contain ONE concrete anchor (park/square/transit stop/micro-area).
- Each "why" bullet length: 12–18 words (enough detail to wrap to ~3 lines total in PDF when combined).
- Avoid semicolons and long chaining. One finished sentence per bullet.

Watch-out rules (VERY IMPORTANT):
- "watch_out" must be one practical risk (noise, budget stretch, commute, parking).
- It must be "smart" and concrete, not generic.
- It must be written as ONE sentence that can wrap to 1–2 lines in PDF.
- watch_out length target: 10–18 words.
- Avoid endings that look truncated; never end with "and/with/to/near/at/via" etc.

Resources rules:
- real_estate_sites and agencies MUST include working URLs with https:// whenever possible.
- Keep note very short (<= 8 words). URLs must not be empty if a known official site exists.

Questions section:
- questions_for_agent_landlord MUST be exactly 5 questions.
- Tailor questions to the mode:
  - RENT: deposit/fees, utilities, lease term/termination, rules/noise, indexation/registration
  - BUY: total costs, legal compliance, building charges/works, condition/inspection, timeline/negotiation

For each of the 3 top_districts include:
- name (string)
- micro_anchors (list of 2-3 strings from city pack micro_anchors)
- microhoods (list of 2-3 objects): each has name (must be from that commune's microhoods shortlist), why (1 sentence), watch_out (1 sentence).
- why (list of 2 strings)
- watch_out (list of 1 string)
- scores (object with 1-5 ints): Safety, Family, Commute, Lifestyle, BudgetFit, Overall (ALL REQUIRED).
"""


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output.")
    return text[start : end + 1]


def _client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=api_key)


def _save_debug_raw(tag: str, raw_text: str) -> None:
    try:
        debug_dir = Path(__file__).resolve().parent.parent / "outputs"
        debug_dir.mkdir(exist_ok=True)
        (debug_dir / f"debug_{tag}.txt").write_text(raw_text, encoding="utf-8")
    except Exception:
        pass




def _extract_resp_text(resp) -> str:
    """Safely extract text from OpenAI Responses API objects across SDK versions.

    Returns '' if no user-visible text exists (tool-only output, refusal, or SDK mismatch).
    """
    if resp is None:
        return ""
    # Common convenience fields
    for attr in ("output_text", "text"):
        v = getattr(resp, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()

    out = getattr(resp, "output", None)
    if out and isinstance(out, list):
        try:
            for item in out:
                content = getattr(item, "content", None)
                if content and isinstance(content, list):
                    for c in content:
                        t = getattr(c, "text", None)
                        if isinstance(t, str) and t.strip():
                            return t.strip()
        except Exception:
            pass
    return ""
def _parse_json_with_repair(client: OpenAI, model: str, raw_text: str, tag: str) -> Dict[str, Any]:
    _save_debug_raw(tag, raw_text)

    try:
        return json.loads(_extract_json(raw_text))
    except JSONDecodeError:
        pass
    except Exception:
        pass

    repair = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": "You are a JSON repair assistant. Return ONLY valid JSON. No markdown. No commentary.",
            },
            {"role": "user", "content": "Fix this into valid JSON. Keep the same structure and keys:\n\n" + raw_text},
        ],
    )

    fixed = _extract_resp_text(repair)
    if not fixed:
        raise RuntimeError("Empty model response during JSON repair")

    _save_debug_raw(tag + "_repaired", fixed)
    return json.loads(_extract_json(fixed))



def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _rank_communes_by_tags(pack: Dict[str, Any], priority_ids: list[str], top3_ids: list[str], k: int = 7) -> list[Dict[str, Any]]:
    communes = pack.get("communes") or []
    if not communes:
        # Legacy packs don't have communes; caller should fallback.
        return []

    weights = {tid: 3 for tid in top3_ids}
    for tid in priority_ids:
        weights.setdefault(tid, 1)

    scored = []
    for c in communes:
        c_tags = c.get("tags") or []
        score = 0
        for t in c_tags:
            if t in weights:
                score += weights[t]
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    # If everything is zero, fallback to default shortlist if present, else first k
    if scored and scored[0][0] == 0:
        default = pack.get("default_shortlist") or []
        if default:
            name_set = set([n.lower() for n in default])
            ordered = [c for _, c in scored if str(c.get("name","")).lower() in name_set]
            return ordered[:k] if ordered else [c for _, c in scored[:k]]
        return [c for _, c in scored[:k]]

    return [c for _, c in scored[:k]]


def _compact_pack_for_llm(pack: Dict[str, Any], shortlist_communes: list[Dict[str, Any]], priority_ids: list[str], top3_ids: list[str]) -> Dict[str, Any]:
    # Keep only what LLM needs to decide and write premium copy.
    vocab = pack.get("tags_vocab") or []
    vocab_map = {t.get("id"): {"title": t.get("title"), "sub": t.get("sub")} for t in vocab if t.get("id")}
    user_tags = []
    for tid in priority_ids:
        meta = vocab_map.get(tid, {})
        user_tags.append({
            "id": tid,
            "title": meta.get("title", tid),
            "weight": 3 if tid in top3_ids else 1
        })

    communes_out = []
    microhood_commune = _load_microhood_commune_map()
    for c in shortlist_communes:
        # Microhood shortlist (names only + a tiny hint) so the model can pick 2–3 per commune.
        mh_short = []
        for mh in (c.get("microhoods") or [])[:8]:
            if not isinstance(mh, dict) or not mh.get("name"):
                continue
            owner = microhood_commune.get(re.sub(r"\s+", " ", str(mh.get("name") or "").strip().lower()))
            if owner and owner != str(c.get("name") or "").strip():
                continue
            hint_parts = []
            m = mh.get("metrics") or {}
            if isinstance(m, dict):
                if (m.get("parks_share") or 0) >= 0.16:
                    hint_parts.append("greener")
                if (m.get("cafes_density") or 0) >= 0.55:
                    hint_parts.append("lively")
                if (m.get("tram_stop_density") or 0) >= 0.55 or (m.get("metro_stop_density") or 0) >= 0.30:
                    hint_parts.append("good transit")
            mh_short.append({"name": mh.get("name"), "hint": ", ".join(hint_parts[:2])})

        communes_out.append({
            "name": c.get("name"),
            "micro_anchors": c.get("micro_anchors", []),
            "tags": c.get("tags", []),
            "watch_out_hint": c.get("watch_out_hint", ""),
            "tag_confidence": {k:v for k,v in (c.get("tag_confidence") or {}).items() if k in (c.get("tags") or [])},
            "microhoods_shortlist": mh_short,
        })

    return {
        "city": pack.get("city"),
        "level": pack.get("level", "commune"),
        "tags_vocab": [{"id": t.get("id"), "title": t.get("title")} for t in vocab if t.get("id")],
        "user_priority_tags": user_tags,
        "communes_shortlist": communes_out,
        "real_estate_sites": pack.get("real_estate_sites", [])[:3],
        "agencies": pack.get("agencies", [])[:5],
        "rules": {
            "district_selection": "Choose top_districts ONLY from communes_shortlist names.",
            "anchors": "Use micro_anchors inside why bullets (one anchor per bullet).",
            "tags": "Use only tags from tags_vocab."
        }
    }


def _norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _enforce_communes_on_top_districts(
    brief: Dict[str, Any],
    communes_shortlist: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Ensure top_districts[].name are ONLY commune names from communes_shortlist.

    If the model outputs an invalid name (e.g., a micro-area like "European Quarter"),
    we replace it deterministically with the next best unused commune from the shortlist.
    We also attach micro_anchors from the pack so the PDF can show them in parentheses.
    """
    td = brief.get("top_districts")
    if not isinstance(td, list) or not communes_shortlist:
        return brief

    allowed = [c.get("name") for c in communes_shortlist if c.get("name")]
    allowed_norm = {_norm_label(n): n for n in allowed}
    commune_by_name = {c.get("name"): c for c in communes_shortlist if c.get("name")}

    used = set()
    fixed = []
    for item in td:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name", "")).strip()
        # Exact / normalized match to allowed communes
        name = allowed_norm.get(_norm_label(raw_name), None)
        if not name:
            # Replace with next unused commune from shortlist
            name = next((n for n in allowed if n not in used), None) or (allowed[0] if allowed else raw_name)

        used.add(name)
        item["name"] = name

        # Attach micro_anchors (2-3) from pack shortlist
        c = commune_by_name.get(name, {})
        ma = c.get("micro_anchors") or []
        if isinstance(ma, list):
            item.setdefault("micro_anchors", ma[:3])
        else:
            item.setdefault("micro_anchors", [])

        fixed.append(item)

    # Ensure exactly 3 districts (pad from shortlist if needed)
    if len(fixed) < 3:
        for n in allowed:
            if n in used:
                continue
            fixed.append({"name": n, "micro_anchors": (commune_by_name.get(n, {}).get("micro_anchors") or [])[:3], "why": [], "watch_out": [], "scores": {}})
            used.add(n)
            if len(fixed) == 3:
                break
    brief["top_districts"] = fixed[:3]
    return brief

def _enforce_microhoods_on_top_districts(
    brief: Dict[str, Any],
    communes_shortlist: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Ensure microhood names are selected from the per-commune microhood shortlist.

    If the model invents a microhood or returns something not in the shortlist,
    we deterministically replace it with the top unused microhood from that commune.
    """
    td = brief.get("top_districts")
    if not isinstance(td, list) or not communes_shortlist:
        return brief

    commune_by_name = {c.get("name"): c for c in communes_shortlist if c.get("name")}
    microhood_commune = _load_microhood_commune_map()
    for item in td:
        if not isinstance(item, dict):
            continue
        cname = item.get("name")
        c = commune_by_name.get(cname, {})
        allowed = []
        for mh in (c.get("microhoods") or []):
            if not isinstance(mh, dict) or not mh.get("name"):
                continue
            nm = str(mh.get("name") or "").strip()
            owner = microhood_commune.get(re.sub(r"\s+", " ", nm.lower()))
            if owner and owner != str(cname or "").strip():
                continue
            allowed.append(nm)
        allowed_norm = {_norm_label(n): n for n in allowed}
        if not allowed:
            continue

        mh_out = item.get("microhoods")
        if not isinstance(mh_out, list):
            # Create minimal placeholder list
            item["microhoods"] = [{"name": allowed[0], "why": "", "watch_out": ""}, {"name": allowed[1] if len(allowed)>1 else allowed[0], "why": "", "watch_out": ""}]
            continue

        used = set()
        fixed_mh = []
        for mho in mh_out[:3]:
            if not isinstance(mho, dict):
                continue
            raw = str(mho.get("name","")).strip()
            nm = allowed_norm.get(_norm_label(raw), None)
            if not nm:
                nm = next((n for n in allowed if n not in used), allowed[0])
            used.add(nm)
            mho["name"] = nm
            fixed_mh.append(mho)

        # pad to 2..3
        while len(fixed_mh) < 2:
            nm = next((n for n in allowed if n not in used), allowed[0])
            used.add(nm)
            fixed_mh.append({"name": nm, "why": "", "watch_out": ""})

        item["microhoods"] = fixed_mh[:3]

    return brief

def _get_models() -> tuple[str, str]:
    # Draft should be fast; Final can be higher quality.
    default = os.environ.get("MODEL", "gpt-4o-mini")
    draft = os.environ.get("MODEL_DRAFT", default)
    final = os.environ.get("MODEL_FINAL", os.environ.get("MODEL", "gpt-5"))
    return draft, final



def _validate_brief(obj: Dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["root must be an object"]

    cp = (obj.get("client_profile") or "")
    if not isinstance(cp, str):
        errors.append("client_profile must be string")
    elif len(cp) > 230:
        errors.append("client_profile must be <= 230 chars")

    def _check_list(key: str, max_len: int | None = None, exact: int | None = None):
        v = obj.get(key, [])
        if not isinstance(v, list):
            errors.append(f"{key} must be a list")
            return []
        if exact is not None and len(v) != exact:
            errors.append(f"{key} must have exactly {exact} items")
        if max_len is not None and len(v) > max_len:
            errors.append(f"{key} must have <= {max_len} items")
        return v

    _check_list("must_have", max_len=5)
    _check_list("nice_to_have", max_len=5)
    _check_list("red_flags", max_len=5)
    _check_list("contradictions", max_len=4)
    _check_list("next_steps", max_len=4)
    _check_list("clarifying_questions", max_len=5)
    _check_list("questions_for_agent_landlord", exact=5)

    td = _check_list("top_districts", exact=3)
    for i, d in enumerate(td):
        if not isinstance(d, dict):
            errors.append(f"top_districts[{i}] must be object")
            continue
        why = d.get("why", [])
        if not isinstance(why, list) or len(why) != 2:
            errors.append(f"top_districts[{i}].why must have exactly 2 bullets")
        wo = d.get("watch_out", [])
        if not isinstance(wo, list) or len(wo) != 1:
            errors.append(f"top_districts[{i}].watch_out must have exactly 1 bullet")
        mh = d.get("microhoods", [])
        if not isinstance(mh, list) or not (2 <= len(mh) <= 3):
            errors.append(f"top_districts[{i}].microhoods must have 2..3 items")
        else:
            for j, mho in enumerate(mh):
                if not isinstance(mho, dict):
                    errors.append(f"top_districts[{i}].microhoods[{j}] must be object")
                    continue
                if not isinstance(mho.get("name", ""), str) or not mho.get("name"):
                    errors.append(f"top_districts[{i}].microhoods[{j}].name must be string")
                if not isinstance(mho.get("why", ""), str) or len(str(mho.get("why",""))) > 160:
                    errors.append(f"top_districts[{i}].microhoods[{j}].why must be <= 160 chars")
                if not isinstance(mho.get("watch_out", ""), str) or len(str(mho.get("watch_out",""))) > 160:
                    errors.append(f"top_districts[{i}].microhoods[{j}].watch_out must be <= 160 chars")

        scores = d.get("scores", {})
        if not isinstance(scores, dict):
            errors.append(f"top_districts[{i}].scores must be object")
        else:
            for k in ["Safety", "Family", "Commute", "Lifestyle", "BudgetFit", "Overall"]:
                if k not in scores:
                    errors.append(f"top_districts[{i}].scores missing {k}")
                else:
                    try:
                        v = int(scores[k])
                        if v < 1 or v > 5:
                            errors.append(f"top_districts[{i}].scores.{k} must be 1..5")
                    except Exception:
                        errors.append(f"top_districts[{i}].scores.{k} must be int")
    return errors


def _maybe_polish_invalid_json(client: OpenAI, model: str, obj: Dict[str, Any], errors: list[str]) -> Dict[str, Any]:
    # One fast "polish" call if structure doesn't meet hard constraints.
    if not errors:
        return obj
    prompt = (
        "Fix this JSON to satisfy the constraints below, without changing the overall meaning. "
        "Return ONLY valid JSON, same keys. Constraints:\n"
        + "\n".join([f"- {e}" for e in errors])
        + "\n\nJSON:\n"
        + json.dumps(obj, ensure_ascii=False)
    )
    resp = client.responses.create(
        model=model,
        max_output_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS_POLISH", "800")),
        input=[
            {"role": "system", "content": "You are a strict JSON editor. Return ONLY valid JSON. No commentary."},
            {"role": "user", "content": prompt},
        ],
    )
    raw = _extract_resp_text(resp)

    if not raw:
        # Fail-soft: deterministic minimal brief from shortlist
        return _fallback_brief_from_shortlist(
            normalized={"location": answers.get("city", "")},
            communes_shortlist=shortlist,
            pack=pack,
        )
    fixed = _parse_json_with_repair(client, model, raw, tag="polish")
    return fixed

def _fallback_brief_from_shortlist(
    normalized: Dict[str, Any],
    communes_shortlist: list[Dict[str, Any]],
    pack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministic minimal brief used when the model returns an empty response.

    Keeps the system usable and consistent: areas/microhoods come ONLY from pack shortlist.
    """
    city = (normalized or {}).get("location") or (pack or {}).get("city") or ""
    # pick first 3 communes (or fewer)
    td = []
    for c in (communes_shortlist or [])[:3]:
        scores = {k: 3 for k in ["Safety","Family","Commute","Lifestyle","BudgetFit","Overall"]}
        micro_anchors = c.get("micro_anchors") or []
        # choose 2 microhoods if available
        mh_names = [mh.get("name") for mh in (c.get("microhoods") or []) if isinstance(mh, dict) and mh.get("name")]
        microhoods = []
        for nm in mh_names[:2]:
            microhoods.append({"name": nm, "why": "", "watch_out": ""})
        if len(microhoods) < 2 and mh_names:
            microhoods.append({"name": mh_names[0], "why": "", "watch_out": ""})

        td.append({
            "name": c.get("name") or "",
            "micro_anchors": micro_anchors[:3],
            "scores": scores,
            "matched_priorities": {"strong": [], "medium": []},
            "why": [""],
            "watch_out": [c.get("watch_out_hint","")[:140]] if c.get("watch_out_hint") else [""],
            "microhoods": microhoods,
        })

    resources = []
    # pull pack-level allowlisted resources if present
    if isinstance((pack or {}).get("resources"), list):
        for r in (pack or {}).get("resources")[:8]:
            if isinstance(r, dict) and r.get("url") and r.get("label"):
                resources.append(r)

    return {
        "city": city,
        "scores": {k: 3 for k in ["Safety","Family","Commute","Lifestyle","BudgetFit","Overall"]},
        "top_districts": td,
        "resources": resources,
        "client_profile": "",
        "must_have": [],
        "nice_to_have": [],
        "red_flags": [],
        "contradictions": [],
        "next_steps": [],
        "clarifying_questions": [],
        "questions_for_agent_landlord": [],
    }

def draft_brief(answers: Dict[str, str], quality: bool = False) -> Dict[str, Any]:
    model_draft, model_final = _get_models()
    model = model_final if quality else model_draft
    client = _client()

    pack = load_city_pack(answers.get("city", ""))
    # Build shortlist using tags if pack supports it
    priority_ids = _split_csv(answers.get("priority_tag_ids", ""))
    top3_ids = _split_csv(answers.get("priority_top3_ids", ""))

    shortlist = _rank_communes_by_tags(pack, priority_ids, top3_ids, k=int(os.environ.get("SHORTLIST_K", "7"))) if pack else []
    if pack and shortlist:
        pack_obj = _compact_pack_for_llm(pack, shortlist, priority_ids, top3_ids)
        pack_text = "City pack (shortlist reference):\n" + json.dumps(pack_obj, ensure_ascii=False)
    else:
        # Legacy behavior: include only district_hints if present (avoid huge dumps)
        legacy = {}
        if pack and pack.get("district_hints"):
            legacy = {
                "city": pack.get("city"),
                "district_hints": pack.get("district_hints"),
                "real_estate_sites": pack.get("real_estate_sites", [])[:3],
                "agencies": pack.get("agencies", [])[:5],
            }
        pack_text = "" if not legacy else ("City pack (reference):\n" + json.dumps(legacy, ensure_ascii=False))

    input_lines = [f"{k}: {v}" for k, v in answers.items() if v is not None and str(v).strip() != ""]
    intake = "Client intake answers:\n" + "\n".join(input_lines)

    resp = client.responses.create(
        model=model,
        max_output_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS_FINAL" if quality else "MAX_OUTPUT_TOKENS_DRAFT", "1400" if quality else "1200")),
        input=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            *([{"role": "user", "content": pack_text}] if pack_text else []),
            {"role": "user", "content": intake},
            {
                "role": "user",
                "content": (
                    "Return ONLY a JSON object with keys: "
                    "client_profile, must_have, nice_to_have, red_flags, contradictions, "
                    "top_districts (exactly 3 objs), real_estate_sites, agencies, "
                    "questions_for_agent_landlord (exactly 5), next_steps, "
                    "clarifying_questions (max 5). "
                    "For real_estate_sites/agencies items include name,url,note. "
                    "For top_districts.scores always include Safety, Family, Commute as integers 1..5. "
                    "Remember: no truncated bullets, ASCII only, client_profile <= 230 chars. "
                    "Top districts why bullets must be 12–18 words each. "
                    "Watch-out must be 10–18 words and wrap to 1–2 lines."
                ),
            },
        ],
    )

    raw = _extract_resp_text(resp)

    if not raw:
        # Fail-soft: deterministic brief from the pack shortlist
        return _fallback_brief_from_shortlist({"location": answers.get("city", "")}, shortlist, pack)

    parsed = _parse_json_with_repair(client, model, raw, tag="draft")
    errs = _validate_brief(parsed)
    parsed = _maybe_polish_invalid_json(client, model, parsed, errs)
    # Hard guardrail: district names must be communes from shortlist
    if pack and shortlist:
        parsed = _enforce_communes_on_top_districts(parsed, shortlist)
        parsed = _enforce_microhoods_on_top_districts(parsed, shortlist)
    return parsed


def finalize_brief(
    answers: Dict[str, str],
    current_brief: Dict[str, Any],
    clarifying_answers: Dict[str, str],
) -> Dict[str, Any]:
    _model_draft, model_final = _get_models()
    client = _client()

    pack = load_city_pack(answers.get("city", ""))
    priority_ids = _split_csv(answers.get("priority_tag_ids", ""))
    top3_ids = _split_csv(answers.get("priority_top3_ids", ""))

    shortlist = _rank_communes_by_tags(pack, priority_ids, top3_ids, k=int(os.environ.get("SHORTLIST_K", "7"))) if pack else []
    if pack and shortlist:
        pack_obj = _compact_pack_for_llm(pack, shortlist, priority_ids, top3_ids)
        pack_text = "City pack (shortlist reference):\n" + json.dumps(pack_obj, ensure_ascii=False)
    else:
        legacy = {}
        if pack and pack.get("district_hints"):
            legacy = {
                "city": pack.get("city"),
                "district_hints": pack.get("district_hints"),
                "real_estate_sites": pack.get("real_estate_sites", [])[:4],
                "agencies": pack.get("agencies", [])[:3],
            }
        pack_text = "" if not legacy else ("City pack (reference):\n" + json.dumps(legacy, ensure_ascii=False))

    input_lines = [f"{k}: {v}" for k, v in answers.items() if v is not None and str(v).strip() != ""]
    intake = "Client intake answers:\n" + "\n".join(input_lines)

    resp = client.responses.create(
        model=model_final,
        max_output_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS_FINAL", "1400")),
        input=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            *([{"role": "user", "content": pack_text}] if pack_text else []),
            {"role": "user", "content": intake},
            {"role": "user", "content": "Current brief JSON:\n" + json.dumps(current_brief, ensure_ascii=False)},
            {"role": "user", "content": "Clarifying answers:\n" + json.dumps(clarifying_answers, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "Update the brief accordingly and return ONLY the updated JSON object (same keys). "
                    "Ensure: client_profile <= 230 chars; each district why has exactly 2 bullets; watch_out exactly 1 bullet. "
                    "Why bullets must be 12–18 words each. "
                    "Watch-out must be 10–18 words and wrap to 1–2 lines. "
                    "No truncated phrases; avoid ending bullets with prepositions or street tokens."
                ),
            },
        ],
    )

    raw = _extract_resp_text(resp)

    if not raw:
        _save_debug_raw("final_empty", "")
        return current_brief

    try:
        parsed = _parse_json_with_repair(client, model_final, raw, tag="final")
        errs = _validate_brief(parsed)
        parsed = _maybe_polish_invalid_json(client, model_final, parsed, errs)
        # Hard guardrail: district names must be communes from shortlist
        if pack and shortlist:
            parsed = _enforce_communes_on_top_districts(parsed, shortlist)
            parsed = _enforce_microhoods_on_top_districts(parsed, shortlist)
        return parsed
    except Exception:
        _save_debug_raw("final_parse_error", raw)
        return current_brief
