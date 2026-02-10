from typing import Dict, Any, List


def _clean(s: str) -> str:
    if not s:
        return s
    return (
        str(s)
        .replace("\u00A0", " ")
        .replace("\u202F", " ")
        .replace("\u2007", " ")
        .replace("\u2060", "")
        .replace("\u200B", "")
        .replace("\ufeff", "")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("minutes'", "minutes")
        .replace("minute'", "minute")
    )


def _bullets(items: List[str]) -> str:
    if not items:
        return "- —"
    return "\n".join([f"- {_clean(x)}" for x in items])


def _numbered(items: List[str]) -> str:
    if not items:
        return "1. —"
    lines = []
    for i, x in enumerate(items, 1):
        lines.append(f"{i}. {_clean(x)}")
    return "\n".join(lines)


def _md_link(name: str, url: str) -> str:
    name = _clean(name or "—")
    url = (url or "").strip()
    if url:
        return f"[{name}]({url})"
    return name


def _links(items) -> str:
    if not items:
        return "- —"
    lines = []
    for x in items:
        if isinstance(x, dict):
            name = x.get("name", "—")
            url = x.get("url", "")
            note = _clean(x.get("note", ""))
            link = _md_link(name, url)
            if note:
                lines.append(f"- {link} — {note}")
            else:
                lines.append(f"- {link}")
        else:
            lines.append(f"- {_clean(x)}")
    return "\n".join(lines)


def _score_line(scores: Dict[str, Any]) -> str:
    keys = ["Safety", "Family", "Commute", "Lifestyle", "BudgetFit", "Overall"]
    parts = [f"{k}:{scores[k]}" for k in keys if k in scores]
    return " | ".join(parts) if parts else "—"


def render_md(b: Dict[str, Any], city: str) -> str:
    # Executive summary (quick scan)
    exec_lines: List[str] = []
    exec_rows = b.get("executive_summary") or []
    if isinstance(exec_rows, list) and exec_rows:
        exec_lines.append("| Commune | Best for | Watch-outs | Top microhoods |")
        exec_lines.append("|---|---|---|---|")
        for row in exec_rows[:3]:
            if not isinstance(row, dict):
                continue
            name = _clean(row.get("name", "—"))
            best = _clean(row.get("best_for", "—")).replace("…", "")
            watch = _clean(row.get("watch_out", "—")).replace("…", "")
            mhs = [
                _clean(x)
                for x in (row.get("top_microhoods") or [])
                if _clean(x)
            ][:3]
            mh_txt = " · ".join(mhs) if mhs else "—"
            exec_lines.append(f"| {name} | {best} | {watch} | {mh_txt} |")
    exec_section = "\n".join(exec_lines) if exec_lines else "—"
    districts = []
    for i, d in enumerate(b.get("top_districts", []), 1):
        why = d.get("why", []) or []
        watch = d.get("watch_out", []) or []
        snap = d.get("priority_snapshot") or {}
        snap_lines = []
        if snap:
            key_map = {
                "housing_cost": "Typical housing cost",
                "transit": "Public transport",
                "commute_access": "Commute access",
                "schools_family": "Schools & family",
            }
            for k in ["housing_cost", "transit", "commute_access", "schools_family"]:
                v = snap.get(k)
                if v:
                    snap_lines.append(f"- {key_map[k]}: {_clean(v)}")
        microhoods = []
        for mh in (d.get("microhoods") or [])[:3]:
            if not isinstance(mh, dict):
                continue
            name = _clean(mh.get("name", "—"))
            kws = mh.get("portal_keywords") or mh.get("keywords") or []
            if isinstance(kws, str):
                kws = [kws]
            if not isinstance(kws, list):
                kws = []
            kws = [k for k in [_clean(x) for x in kws] if k][:6]
            kw_txt = ", ".join(kws) if kws else "—"

            hl = _clean(mh.get("highlights") or "")
            if not hl:
                # Backwards compatibility: some datasets still have why/watch_out.
                why = _clean(mh.get("why") or "")
                wo = _clean(mh.get("watch_out") or "")
                hl = " ".join([p for p in [why, wo] if p]).strip()
            if not hl:
                hl = "—"

            microhoods.append(
                f"**{name}**\n  - Portal keywords: {kw_txt}\n  - Highlights: {hl}"
            )
        districts.append(
            f"### {i}) {_clean(d.get('name','—'))}\n"
            f"**Scorecard (1–5):** {_score_line(d.get('scores',{}))}\n\n"
            f"**Why:**\n{_bullets(why)}\n\n"
            f"**Watch-out:**\n{_bullets(watch)}\n"
            + (f"\n\n**Priorities snapshot:**\n{chr(10).join(snap_lines) if snap_lines else '- —'}\n" if True else "")
            + (f"\n\n**Microhoods to start with:**\n{_bullets(microhoods)}\n" if True else "")
        )

    return f"""# Relocation Brief — {_clean(city)}

## Client profile
{_clean(b.get('client_profile',''))}

## Executive summary (quick scan)
{exec_section}

## Must-have
{_bullets(b.get('must_have', []))}

## Nice-to-have
{_bullets(b.get('nice_to_have', []))}

## Red flags
{_bullets(b.get('red_flags', []))}

## Trade-offs
{_bullets(b.get('contradictions', []))}

## Top-3 areas (shortlist)
{chr(10).join(districts)}

## Next steps
{_bullets(b.get('next_steps', []))}

## Resources

### Websites
{_numbered([_md_link(x.get('name','—'), x.get('url','')) + (f" — {_clean(x.get('note',''))}" if _clean(x.get('note','')) else "") for x in (b.get('real_estate_sites') or []) if isinstance(x, dict)])}

### Agencies
{_numbered([_md_link(x.get('name','—'), x.get('url','')) + (f" — {_clean(x.get('note',''))}" if _clean(x.get('note','')) else "") for x in (b.get('agencies') or []) if isinstance(x, dict)])}

## Essentials to ask your Real Estate agent
{_bullets(b.get('questions_for_agent_landlord', []))}

## Clarifying questions (if needed)
{_bullets(b.get('clarifying_questions', []))}
"""
