from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# ---------- Markdown chunking / anchors ----------

_slug_re = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    s = (text or "").strip().lower()
    s = _slug_re.sub("-", s).strip("-")
    return s or "section"


@dataclass
class MdChunk:
    title: str
    anchor: str
    level: int
    text: str


def split_md_by_headings(md: str) -> List[MdChunk]:
    """
    Split markdown into chunks by headings (## / ### / ####...).
    Each chunk includes the heading line and following content until next heading of same or higher level.
    """
    lines = (md or "").splitlines()
    chunks: List[MdChunk] = []

    current_title: Optional[str] = None
    current_level: int = 0
    current_lines: List[str] = []

    def flush():
        nonlocal current_title, current_level, current_lines
        if current_title is None:
            return
        text = "\n".join(current_lines).strip()
        chunks.append(
            MdChunk(
                title=current_title,
                anchor=_slugify(current_title),
                level=current_level,
                text=text,
            )
        )

    heading_re = re.compile(r"^(#{2,6})\s+(.*)\s*$")  # start at ##
    for ln in lines:
        m = heading_re.match(ln)
        if m:
            hashes = m.group(1)
            title = m.group(2).strip()
            level = len(hashes)
            # start new chunk
            flush()
            current_title = title
            current_level = level
            current_lines = [ln]
        else:
            if current_title is None:
                # ignore preamble (H1 title etc.) for retrieval
                continue
            current_lines.append(ln)

    flush()
    return chunks


def _tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    parts = [p for p in text.split() if len(p) >= 2]
    return parts


def rank_chunks(question: str, chunks: List[MdChunk], top_k: int = 6) -> List[Tuple[MdChunk, float]]:
    """
    Simple keyword scoring (MVP): sum of term matches + small bonus for title matches.
    """
    q_terms = _tokenize(question)
    if not q_terms:
        return [(c, 0.0) for c in chunks[:top_k]]

    q_set = set(q_terms)
    ranked: List[Tuple[MdChunk, float]] = []
    for c in chunks:
        hay = (c.text or "").lower()
        title = (c.title or "").lower()
        score = 0.0
        # term frequency-ish
        for t in q_set:
            if t in title:
                score += 2.5
            if t in hay:
                # count occurrences, capped
                cnt = hay.count(t)
                score += min(6, cnt) * 1.0
        # prefer higher-level headings slightly (## over ####)
        score += max(0.0, 0.6 - 0.1 * (c.level - 2))
        ranked.append((c, score))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:top_k]


# ---------- Verified lookup (Tavily) ----------

DEFAULT_OFFICIAL_DOMAINS = [
    "brussels.be",
    "be.brussels",
    "environnement.brussels",
    "environment.brussels",
    "ibsa.brussels",
    "bisa.brussels",
    "statbel.fgov.be",
]


def _official_domains() -> List[str]:
    raw = (os.environ.get("OFFICIAL_DOMAINS") or "").strip()
    if raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return parts or DEFAULT_OFFICIAL_DOMAINS
    return DEFAULT_OFFICIAL_DOMAINS


def tavily_search_official(query: str, *, max_results: int = 5, timeout_s: int = 25) -> List[Dict[str, Any]]:
    """
    Search the web using Tavily, restricted to an allowlist of official domains.
    Returns a list of {url,title,content} objects.
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set (required for verified lookup).")

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": int(max_results),
        "include_domains": _official_domains(),
        "search_depth": os.environ.get("TAVILY_SEARCH_DEPTH", "basic"),
        "include_answer": False,
        "include_raw_content": False,
    }
    resp = requests.post("https://api.tavily.com/search", json=payload, timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json() or {}
    out: List[Dict[str, Any]] = []
    for r in data.get("results", []) or []:
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if not url or not content:
            continue
        out.append({"url": url, "title": title, "content": content})
    return out


def _pick_verified_excerpts(question: str, results: List[Dict[str, Any]], max_excerpts: int = 4) -> List[Dict[str, Any]]:
    """
    Take Tavily snippets and pick the most relevant excerpts.
    We keep them short to avoid prompt bloat and to keep citations crisp.
    """
    q_terms = set(_tokenize(question))
    scored: List[Tuple[Dict[str, Any], float]] = []
    for r in results:
        text = (r.get("content") or "").lower()
        score = 0.0
        for t in q_terms:
            if t in text:
                score += min(6, text.count(t))
        scored.append((r, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    picked = [r for r, _ in scored[:max_excerpts]]
    # truncate content
    for r in picked:
        c = r.get("content") or ""
        if len(c) > 850:
            r["content"] = c[:850].rsplit(" ", 1)[0] + "…"
    return picked


# ---------- LLM call ----------

def _openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    # Lazy import to keep the module importable even if openai isn't installed
    # in environments where QA is not used.
    from openai import OpenAI  # type: ignore

    return OpenAI(api_key=api_key)


def _extract_resp_text(resp: Any) -> str:
    if resp is None:
        return ""
    if hasattr(resp, "output_text") and resp.output_text:
        return resp.output_text
    # Fallback: try to walk output
    try:
        out = []
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", None) == "output_text":
                    out.append(getattr(c, "text", ""))
        return "\n".join([x for x in out if x])
    except Exception:
        return ""


def _safe_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction.

    Models occasionally wrap JSON in markdown fences, add prose before/after,
    or return slightly-invalid JSON. For MVP robustness, we try:
    1) direct json.loads
    2) extract the first {...} block and json.loads

    We intentionally keep this conservative: if we can't parse, return None.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # common markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()

    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # Extract first JSON object by brace matching
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    end = -1
    for i in range(start, len(raw)):
        ch = raw[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    snippet = raw[start : end + 1]
    try:
        obj = json.loads(snippet)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _norm_top_districts(norm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return top districts/communes list from norm.json across versions."""
    td = norm.get("top_districts")
    if isinstance(td, list) and td:
        return td
    # older/alternate keys
    for k in ("top_communes", "top_communes_ranked", "districts"):
        v = norm.get(k)
        if isinstance(v, list) and v:
            return v
    return []


def _find_district_mention(question: str, districts: List[Dict[str, Any]]) -> Optional[str]:
    q = (question or "").lower()
    names: List[str] = []
    for d in districts:
        n = (d.get("name") or d.get("commune") or "").strip()
        if n:
            names.append(n)
    # longest match first
    names.sort(key=len, reverse=True)
    for n in names:
        if n.lower() in q:
            return n
    return None


def _slug_to_anchor_from_md(md_text: str, contains: str) -> Tuple[str, str]:
    """Pick a reasonable anchor/snippet by scanning chunk titles."""
    contains_l = (contains or "").lower()
    for c in split_md_by_headings(md_text or ""):
        if contains_l in (c.title or "").lower():
            snip = (c.text or "").strip().splitlines()
            sn = "\n".join(snip[:3]).strip()
            if len(sn) > 220:
                sn = sn[:220].rsplit(" ", 1)[0] + "…"
            return c.anchor, sn
    return "", ""


def _deterministic_why_rank_answer(
    *,
    question: str,
    md_text: str,
    norm: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Answer ranking/"why" questions directly from norm.json.

    This avoids brittle retrieval and does not depend on LLM formatting.
    """
    q = (question or "").strip()
    ql = q.lower()
    districts = _norm_top_districts(norm)
    if not districts:
        return None

    is_rank_q = any(x in ql for x in ("why", "rank", "first", "#1", "top", "higher", "lower", "compare"))
    if not is_rank_q:
        return None

    mentioned = _find_district_mention(q, districts)

    # Simple compare pattern: "X vs Y" or "X higher than Y"
    compare = None
    m_vs = re.search(r"(.+?)\s+(?:vs\.?|versus)\s+(.+)", q, flags=re.IGNORECASE)
    if m_vs:
        compare = (m_vs.group(1).strip(), m_vs.group(2).strip())
    m_higher = re.search(r"(.+?)\s+(?:higher than|above)\s+(.+)", q, flags=re.IGNORECASE)
    if m_higher:
        compare = (m_higher.group(1).strip(), m_higher.group(2).strip())

    # Build a lookup by normalized name
    def norm_name(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    by_name = {norm_name(d.get("name") or d.get("commune") or ""): d for d in districts if (d.get("name") or d.get("commune"))}

    def get_d(name: str) -> Optional[Dict[str, Any]]:
        if not name:
            return None
        key = norm_name(name)
        if key in by_name:
            return by_name[key]
        # partial/contains match
        for k, v in by_name.items():
            if key in k or k in key:
                return v
        return None

    # If compare, answer comparison
    if compare:
        d1 = get_d(compare[0])
        d2 = get_d(compare[1])
        if d1 and d2:
            n1 = d1.get("name") or d1.get("commune")
            n2 = d2.get("name") or d2.get("commune")
            s1 = d1.get("scores") or {}
            s2 = d2.get("scores") or {}
            # pick top differing dimensions
            dims = [k for k in ("Family", "Safety", "Commute", "Lifestyle", "BudgetFit", "Overall") if k in s1 and k in s2]
            diffs = []
            for k in dims:
                try:
                    diffs.append((k, float(s1.get(k, 0)) - float(s2.get(k, 0))))
                except Exception:
                    continue
            diffs.sort(key=lambda x: abs(x[1]), reverse=True)
            bullets = []
            for k, dv in diffs[:3]:
                if dv == 0:
                    continue
                sign = "+" if dv > 0 else ""
                bullets.append(f"{k}: {n1} {sign}{int(dv)} vs {n2}")

            why1 = (d1.get("score_debug") or d1.get("why") or [])
            why2 = (d2.get("score_debug") or d2.get("why") or [])
            # score_debug may be dict; normalize to list of short reasons
            def reasons(x):
                if isinstance(x, list):
                    return [str(i) for i in x if str(i).strip()][:2]
                if isinstance(x, dict):
                    out=[]
                    for kk,vv in x.items():
                        if isinstance(vv, list) and vv:
                            out.append(f"{kk}: {vv[0]}")
                        elif isinstance(vv, str) and vv.strip():
                            out.append(f"{kk}: {vv}")
                    return out[:2]
                return []
            r1 = reasons(why1)
            r2 = reasons(why2)

            anchor, snip = _slug_to_anchor_from_md(md_text, "Executive summary")
            if not anchor:
                anchor, snip = _slug_to_anchor_from_md(md_text, "Top")
            answer = (
                f"{n1} ranks higher than {n2} in this brief because it matches your priorities better across key scoring dimensions.\n"
                + "\n".join([f"- {b}" for b in bullets[:3]])
            )
            if r1:
                answer += "\n- Key factors for " + str(n1) + ": " + "; ".join(r1)
            if r2:
                answer += "\n- Trade-offs for " + str(n2) + ": " + "; ".join(r2)

            return {
                "answer": answer.strip(),
                "citations": [
                    {"label": "Executive summary", "anchor": anchor, "snippet": snip} if anchor else {"label": "Ranking logic", "anchor": "", "snippet": "Based on top_districts scores and score_debug in norm.json"}
                ],
                "confidence": 0.85,
            }

    # Otherwise, "why first" for a mentioned district
    if ("first" in ql or "#1" in ql or "top" in ql) and ("why" in ql or "rank" in ql or "first" in ql):
        target_name = mentioned or (districts[0].get("name") or districts[0].get("commune"))
        d = get_d(target_name)
        if not d:
            return None

        name = d.get("name") or d.get("commune")
        s = d.get("scores") or {}
        reasons = d.get("score_debug") or d.get("matched_priorities") or d.get("why") or []
        # Normalize reasons to a few readable bullets
        bullets: List[str] = []
        if isinstance(reasons, dict):
            for k, v in reasons.items():
                if isinstance(v, list) and v:
                    bullets.append(f"{k}: {v[0]}")
                elif isinstance(v, str) and v.strip():
                    bullets.append(f"{k}: {v}")
        elif isinstance(reasons, list):
            bullets.extend([str(x) for x in reasons if str(x).strip()])

        # fallback bullets: highlight strongest dimensions
        if not bullets:
            dims = ["Family", "Safety", "Lifestyle", "Commute", "BudgetFit", "Overall"]
            dim_scores = [(k, s.get(k)) for k in dims if k in s]
            for k, v in dim_scores[:3]:
                bullets.append(f"{k}: {v}/5")

        anchor, snip = _slug_to_anchor_from_md(md_text, "Executive summary")
        if not anchor:
            anchor, snip = _slug_to_anchor_from_md(md_text, "Top")

        # If question is about a non-#1 district, explain its position
        pos = None
        for i, dd in enumerate(districts, start=1):
            if norm_name(dd.get("name") or dd.get("commune") or "") == norm_name(name):
                pos = i
                break

        conclusion = f"{name} is ranked #1 for your brief because it best matches your selected priorities and scores strongly on the most relevant dimensions."
        if pos and pos != 1:
            conclusion = f"{name} is ranked #{pos} in your brief because it matches your priorities well, but another commune scores slightly better on your top drivers."

        out = conclusion + "\n" + "\n".join([f"- {b}" for b in bullets[:4]])
        return {
            "answer": out.strip(),
            "citations": [
                {"label": "Executive summary", "anchor": anchor, "snippet": snip} if anchor else {"label": "Ranking logic", "anchor": "", "snippet": "Based on top_districts scores and score_debug in norm.json"}
            ],
            "confidence": 0.9,
        }

    return None


REPORT_ONLY_SYSTEM = """You are a real-estate broker style consultant for relocation.
You must answer STRICTLY based on the provided report excerpts (markdown chunks) and optional structured JSON (scores/score_debug).
Rules:
- Source-only: do not use external knowledge.
- No speculation: if the answer is not present, say: "This is not covered in the report."
- Be concise: 1 short conclusion + 2-4 bullet points. Max 6 sentences total.
- If asked "why a score", explain using score_debug with 2-3 factors.
Return ONLY valid JSON with keys: answer, citations, confidence.
citations must be an array of objects: {label, anchor, snippet}. confidence is 0-1 float.
"""

VERIFIED_SYSTEM = """You are a real-estate broker style consultant for relocation.
You must answer STRICTLY based on the provided official-source excerpts (allowlisted domains) plus the report excerpts/JSON if present.
Rules:
- Prefer the report if it contains the answer; otherwise use official excerpts.
- Do not speculate. If not supported by excerpts, say so.
- Be concise: 1 short conclusion + 2-4 bullet points. Max 7 sentences total.
Return ONLY valid JSON with keys: answer, citations, confidence.
citations must be an array of objects. For official sources, use: {label, url, quote}. For report, use: {label, anchor, snippet}.
confidence is 0-1 float.
"""


def answer_question(
    *,
    brief_id: str,
    question: str,
    md_text: str,
    norm: Dict[str, Any],
    mode: str = "report_only",
) -> Dict[str, Any]:
    """
    mode: 'report_only' or 'verified'
    """
    mode = (mode or "report_only").strip().lower()
    if mode not in ("report_only", "verified"):
        mode = "report_only"

    # --- Deterministic router for common "why / compare / ranking" questions ---
    districts = _norm_top_districts(norm or {})
    ql = (question or "").lower()
    is_why = bool(re.search(r"\bwhy\b", ql)) or "explain" in ql
    is_rank = any(k in ql for k in ["first", "#1", "top", "rank", "higher", "lower", "ahead", "above", "below", "compare"])
    mentioned = _find_district_mention(question, districts)
    if districts and (is_why or "compare" in ql or "higher" in ql) and (mentioned or is_rank):
        # Build a deterministic explanation from norm.json (source of truth).
        top_names = [
            (d.get("name") or d.get("commune") or "").strip()
            for d in districts
            if (d.get("name") or d.get("commune"))
        ]
        # identify target district (default to #1 if asking about "first")
        target = mentioned
        if ("first" in ql or "#1" in ql) and top_names:
            target = target or top_names[0]

        def get_d(name: str) -> Optional[Dict[str, Any]]:
            for d in districts:
                dn = (d.get("name") or d.get("commune") or "").strip()
                if dn.lower() == (name or "").strip().lower():
                    return d
            return None

        d0 = get_d(target) if target else None
        if d0:
            # pick 2-3 reasons: prefer score_debug, then matched_priorities/why
            reasons: List[str] = []
            sd = d0.get("score_debug")
            if isinstance(sd, dict):
                # Take top 3 debug strings by key order preference
                for k in ["Family", "Lifestyle", "BudgetFit", "Safety", "Commute", "Overall"]:
                    v = sd.get(k)
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, str) and item.strip():
                                reasons.append(item.strip())
                            if len(reasons) >= 3:
                                break
                    elif isinstance(v, str) and v.strip():
                        reasons.append(v.strip())
                    if len(reasons) >= 3:
                        break
                # Newer score_debug schema: use matched priorities + strongest dimensions
                if not reasons:
                    mp = d0.get("matched_priorities")
                    if isinstance(mp, list) and mp:
                        reasons.append("Matched priorities: " + ", ".join([str(x) for x in mp[:5]]))
                if not reasons:
                    sc = (sd.get("scores") if isinstance(sd.get("scores"), dict) else d0.get("scores")) or {}
                    if isinstance(sc, dict) and sc:
                        dims = [(k, v) for k, v in sc.items() if k and k != "Overall" and isinstance(v, (int, float))]
                        dims.sort(key=lambda kv: kv[1], reverse=True)
                        for k, v in dims[:2]:
                            reasons.append(f"Strong {k} ({int(v)}/5) for your case")
                if not reasons:
                    b = sd.get("budget") if isinstance(sd.get("budget"), dict) else None
                    if b and b.get("mode"):
                        reasons.append(f"Budget fit is {b.get('final', b.get('base'))}/5 given your {b.get('mode')} budget")
            if not reasons:
                wp = d0.get("why")
                if isinstance(wp, list):
                    reasons.extend([str(x).strip() for x in wp if str(x).strip()][:3])
            if not reasons:
                mp = d0.get("matched_priorities")
                if isinstance(mp, list):
                    reasons.append("Matched priorities: " + ", ".join([str(x) for x in mp[:5]]))

            scores = d0.get("scores") or {}
            overall = None
            if isinstance(scores, dict):
                overall = scores.get("Overall")

            # citation anchor/snippet from MD
            anchor, snippet = _slug_to_anchor_from_md(md_text, "Executive summary")
            if not anchor:
                anchor, snippet = _slug_to_anchor_from_md(md_text, "Top")

            bullets = []
            if overall is not None:
                bullets.append(f"Overall score: {overall}/5")
            for r in reasons[:3]:
                bullets.append(r)

            answer = f"{target} ranks #{top_names.index(target)+1 if target in top_names else 1} for your inputs."
            # keep concise
            if len(bullets) > 0:
                answer += "\n" + "\n".join([f"- {b}" for b in bullets[:4]])

            return {
                "answer": answer,
                "citations": [
                    {"label": "Executive summary", "anchor": anchor, "snippet": snippet}
                ]
                if anchor
                else [],
                "confidence": 0.85,
                "mode": mode,
            }

    chunks = split_md_by_headings(md_text or "")
    ranked = rank_chunks(question, chunks, top_k=6)

    top_chunks = []
    for c, score in ranked:
        if score <= 0 and len(top_chunks) >= 3:
            break
        # keep chunk text compact
        txt = c.text.strip()
        if len(txt) > 1600:
            txt = txt[:1600].rsplit(" ", 1)[0] + "…"
        top_chunks.append({"title": c.title, "anchor": c.anchor, "text": txt})

    # Compact norm.json for QA (avoid huge prompt)
    # Note: current norm schema uses top_districts[] entries (commune + microhoods) instead of top_communes.
    top_districts = _norm_top_districts(norm or {})
    top_districts_compact: List[Dict[str, Any]] = []
    for d in (top_districts or [])[:5]:
        if not isinstance(d, dict):
            continue
        top_districts_compact.append(
            {
                "name": d.get("name") or d.get("commune"),
                "scores": d.get("scores"),
                "score_debug": d.get("score_debug"),
                "why": d.get("why"),
                "watch_out": d.get("watch_out"),
                "strengths": d.get("strengths"),
                "tradeoffs": d.get("tradeoffs"),
                "matched_priorities": d.get("matched_priorities"),
                "top_microhoods": d.get("top_microhoods"),
                "microhoods": d.get("microhoods"),
            }
        )

    norm_compact = {
        "client_profile": norm.get("client_profile"),
        "must_have": norm.get("must_have"),
        "nice_to_have": norm.get("nice_to_have"),
        "executive_summary": norm.get("executive_summary"),
        "top_districts": top_districts_compact,
        "methodology": norm.get("methodology") or norm.get("method") or norm.get("trust_method") or norm.get("trust_and_method"),
        "quality_warnings": norm.get("quality_warnings"),
    }

    official_excerpts: List[Dict[str, Any]] = []
    if mode == "verified":
        # build a stable query (avoid sending too much personal data)
        city = (norm.get("city") or norm_compact.get("city") or "").strip() or "Brussels"
        q = f"{question} {city}"
        results = tavily_search_official(q, max_results=int(os.environ.get("TAVILY_MAX_RESULTS", "6")))
        official_excerpts = _pick_verified_excerpts(question, results, max_excerpts=int(os.environ.get("TAVILY_MAX_EXCERPTS", "4")))

    system = VERIFIED_SYSTEM if mode == "verified" else REPORT_ONLY_SYSTEM

    user_payload = {
        "question": question,
        "report_chunks": top_chunks,
        "norm_json": norm_compact,
        "official_excerpts": official_excerpts,
        "mode": mode,
    }

    client = _openai_client()
    model = os.environ.get("OPENAI_QA_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    temperature = float(os.environ.get("QA_TEMPERATURE", "0.2"))

    t0 = time.perf_counter()
    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        temperature=temperature,
    )
    _ = time.perf_counter() - t0

    raw = _extract_resp_text(resp).strip()
    parsed = _safe_json_from_text(raw)
    if not parsed:
        # Safe fallback (keep UX consistent)
        data = {
            "answer": "I could not generate a reliable answer from the sources provided.",
            "citations": [],
            "confidence": 0.0,
        }
    else:
        data = parsed

    # Normalize citations to expected shape
    citations = data.get("citations") or []
    if not isinstance(citations, list):
        citations = []
    data["citations"] = citations
    try:
        conf = float(data.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    data["confidence"] = max(0.0, min(1.0, conf))
    data["mode"] = mode

    return data


def persist_verified_log(brief_id: str, entry: Dict[str, Any], out_dir: Path) -> None:
    """
    Append a verified lookup record to outputs/<brief_id>.verified.jsonl for auditing/debugging.
    """
    try:
        path = out_dir / f"{brief_id}.verified.jsonl"
        line = json.dumps(entry, ensure_ascii=False)
        path.write_text("", encoding="utf-8") if not path.exists() else None
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
