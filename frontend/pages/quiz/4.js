import React, { useMemo, useState } from 'react'
import { useRouter } from 'next/router'
import Layout from '../../components/Layout'
import { useQuiz, resetQuiz } from '../../components/quizState'
import { ALL_TAGS } from '../../components/tags'


const TOP_TAG_IDS = ['cafes_brunch','restaurants','green_parks','central_access','metro_strong','residential_quiet','families','value_for_money','expats_international','eu_quarter_access']
const MAX_SELECT = 7

function Card({title, sub, selected, rank, onClick}){
  return (
    <div className={selected ? 'choice selected' : 'choice'} onClick={onClick} role="button" tabIndex={0}>
      <div style={{display:'flex',justifyContent:'space-between',gap:12,alignItems:'baseline'}}>
        <p className="choiceTitle" style={{margin:0}}>{title}</p>
        {selected && rank >= 0 && rank < 3 ? (
          <span style={{fontSize:12,opacity:0.9}}>Top {rank+1}</span>
        ) : null}
      </div>
      <p className="choiceSub">{sub}</p>
    </div>
  )
}

export default function Step4(){
  const router = useRouter()
  const { state, setState } = useQuiz()
  const [expanded, setExpanded] = useState(false)

  const selected = state.priorities || []

  const visibleTags = useMemo(()=>{
    if (expanded) return ALL_TAGS
    return ALL_TAGS.filter(t => TOP_TAG_IDS.includes(t.id))
  }, [expanded])

  const toggle = (id) => {
    setState(s => {
      const cur = s.priorities || []
      const has = cur.includes(id)
      if (has) return { ...s, priorities: cur.filter(x=>x!==id) }
      if (cur.length >= MAX_SELECT) return s
      return { ...s, priorities: [...cur, id] }
    })
  }

  const can = (selected.length >= 1)

  return (
    <Layout
      step={4}
      title="Select priorities"
      subtitle={`Pick 1–${MAX_SELECT}. First 3 selected are treated as the strongest signal.`}
      actions={(
        <div className="btnRow">
          <div className="btnLeft">
            <button className="linkBtn" onClick={() => router.push('/quiz/3')}>Back</button>
            <button className="linkBtn" onClick={() => { resetQuiz(setState); router.push('/quiz/1'); }}>Reset</button>
          </div>
          <button className="btn" disabled={!can} onClick={() => router.push('/quiz/5')}>Continue</button>
        </div>
      )}
    >
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:10}}>
        <div style={{fontSize:13,opacity:0.9}}>Selected: {selected.length} / {MAX_SELECT}</div>
        <button className="linkBtn" onClick={() => setExpanded(v=>!v)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      </div>

      <div className="row">
        {visibleTags.map(t => (
          <Card
            key={t.id}
            title={t.title}
            sub={t.sub}
            selected={selected.includes(t.id)}
            rank={selected.indexOf(t.id)}
            onClick={() => toggle(t.id)}
          />
        ))}
      </div>
    </Layout>
  )
}
