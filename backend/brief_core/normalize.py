from __future__ import annotations
from typing import Any, Dict, List
import re, json

LIMITS = {
  'client_profile_chars': 230,
  'must_have': 5,
  'nice_to_have': 5,
  'red_flags': 5,
  'contradictions': 4,
  'questions': 5,
  'next_steps': 4,
  'district_why': 2,
  'district_watch': 1,
  'clarifying_questions': 3,
}

def _as_list(x: Any) -> List[str]:
  if x is None: return []
  if isinstance(x, list): return [str(i).strip() for i in x if str(i).strip()]
  if isinstance(x, str):
    s=x.strip()
    if not s: return []
    parts=[p.strip('-• \t') for p in re.split(r'[\n,;]+', s) if p.strip()]
    return parts if parts else [s]
  return [str(x).strip()]

def _as_str(x: Any) -> str:
  if x is None: return ''
  if isinstance(x, str): return x.strip()
  if isinstance(x, dict): return json.dumps(x, ensure_ascii=False)
  return str(x).strip()

def _trim(lst: List[str], n:int)->List[str]:
  return lst[:n] if n>0 else []

def _score_obj(x: Any) -> Dict[str,int]:
  keys=['Safety','Family','Commute','Lifestyle','BudgetFit','Overall']
  s={}
  if isinstance(x, dict):
    for k in keys:
      v = x.get(k) if k in x else x.get(k.lower())
      if v is None: continue
      try:
        s[k]=max(1,min(5,int(v)))
      except: pass
  for k in ['Safety','Family','Commute','Lifestyle','BudgetFit']:
    s.setdefault(k,3)
  if 'Overall' not in s:
    base=[s[k] for k in ['Safety','Family','Commute','Lifestyle','BudgetFit']]
    s['Overall']=int(round(sum(base)/len(base)))
  return s

def _norm_links(items: Any):
  if items is None: return []
  if isinstance(items, dict): items=[items]
  if isinstance(items, str): items=_as_list(items)
  out=[]
  for it in items:
    if isinstance(it, str):
      out.append({'name':it,'url':'','note':''})
    elif isinstance(it, dict):
      out.append({'name':_as_str(it.get('name','—')) or '—','url':_as_str(it.get('url','')),'note':_as_str(it.get('note',''))})
    else:
      out.append({'name':_as_str(it) or '—','url':'','note':''})
  return out

def _norm_districts(items: Any):
  if items is None: items=[]
  if isinstance(items, dict): items=[items]
  if isinstance(items, str): items=_as_list(items)
  out=[]
  for it in items:
    if isinstance(it, str):
      out.append({'name':it,'why':[],'watch_out':[],'scores':_score_obj({})})
    elif isinstance(it, dict):
      out.append({
        'name':_as_str(it.get('name') or it.get('area') or '—') or '—',
        'why':_trim(_as_list(it.get('why')), LIMITS['district_why']),
        'watch_out':_trim(_as_list(it.get('watch_out')), LIMITS['district_watch']),
        'scores':_score_obj(it.get('scores') or {})
      })
    else:
      out.append({'name':_as_str(it) or '—','why':[],'watch_out':[],'scores':_score_obj({})})
  out=out[:3]
  while len(out)<3:
    out.append({'name':'—','why':[],'watch_out':[],'scores':_score_obj({})})
  for d in out:
    if len(d['why'])<2:
      d['why']=d['why']+['Fits your stated priorities.','Reasonable trade-off vs commute/budget.'][:max(0,2-len(d['why']))]
    d['scores']=_score_obj(d.get('scores',{}))
  return out

def normalize_brief(b: Any) -> Dict[str,Any]:
  if not isinstance(b, dict): b={'client_profile':_as_str(b)}
  b.setdefault('client_profile','')
  b['client_profile']=_as_str(b.get('client_profile',''))[:LIMITS['client_profile_chars']]
  b['must_have']=_trim(_as_list(b.get('must_have')), LIMITS['must_have'])
  b['nice_to_have']=_trim(_as_list(b.get('nice_to_have')), LIMITS['nice_to_have'])
  b['red_flags']=_trim(_as_list(b.get('red_flags')), LIMITS['red_flags'])
  b['contradictions']=_trim(_as_list(b.get('contradictions')), LIMITS['contradictions'])
  b['questions_for_agent_landlord']=_trim(_as_list(b.get('questions_for_agent_landlord')), LIMITS['questions'])
  b['next_steps']=_trim(_as_list(b.get('next_steps')), LIMITS['next_steps'])
  b['clarifying_questions']=_trim(_as_list(b.get('clarifying_questions')), LIMITS['clarifying_questions'])
  b['top_districts']=_norm_districts(b.get('top_districts'))
  b['real_estate_sites']=_norm_links(b.get('real_estate_sites'))
  b['agencies']=_norm_links(b.get('agencies'))
  return b
