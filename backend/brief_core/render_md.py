from typing import Dict, Any, List


def _clean(s: str) -> str:
    if not s:
        return s
    return (
        str(s)
        .replace("\u00A0", " ")
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
    districts = []
    for i, d in enumerate(b.get("top_districts", []), 1):
        why = d.get("why", []) or []
        watch = d.get("watch_out", []) or []
        districts.append(
            f"### {i}) {_clean(d.get('name','—'))}\n"
            f"**Scorecard (1–5):** {_score_line(d.get('scores',{}))}\n\n"
            f"**Why:**\n{_bullets(why)}\n\n"
            f"**Watch-out:**\n{_bullets(watch)}\n"
        )

    return f"""# Relocation Brief — {_clean(city)}

## Client profile
{_clean(b.get('client_profile',''))}

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
{_links(b.get('real_estate_sites', []))}

### Agencies
{_links(b.get('agencies', []))}

## Essentials to ask your Real Estate agent
{_bullets(b.get('questions_for_agent_landlord', []))}

## Clarifying questions (if needed)
{_bullets(b.get('clarifying_questions', []))}
"""
