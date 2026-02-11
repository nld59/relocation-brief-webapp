from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from openai import OpenAI


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

def _openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
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
    norm_compact = {
        "city": norm.get("city"),
        "top_communes": norm.get("top_communes"),
        "top_microhoods": norm.get("top_microhoods"),
        "scores": norm.get("scores"),
        "score_debug": norm.get("score_debug"),
        "method": norm.get("method") or norm.get("trust_method") or norm.get("trust_and_method"),
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
    try:
        data = json.loads(raw)
    except Exception:
        # Safe fallback
        data = {
            "answer": "I could not generate a reliable answer from the sources provided.",
            "citations": [],
            "confidence": 0.0,
        }

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
