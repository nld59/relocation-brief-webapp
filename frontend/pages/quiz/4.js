import React, { useMemo, useState } from 'react'
import { useRouter } from 'next/router'
import Layout from '../../components/Layout'
import { useQuiz, resetQuiz } from '../../components/quizState'

const ALL_TAGS = [
  { id:'cafes_brunch', title:'Cafes & brunch', sub:'Coffee spots, local vibe, weekend brunch' },
  { id:'restaurants', title:'Restaurants', sub:'Dining scene and variety' },
  { id:'nightlife', title:'Nightlife', sub:'Bars, late evenings, lively streets' },
  { id:'culture_museums', title:'Culture & museums', sub:'Museums, theaters, cultural venues' },
  { id:'art_design', title:'Art & design vibe', sub:'Architecture, galleries, creative feel' },
  { id:'shopping', title:'Shopping', sub:'Shops, boutiques, retail streets' },
  { id:'local_market_vibe', title:'Markets & local feel', sub:'Weekend markets, neighborhood vibe' },
  { id:'touristy', title:'Touristy / central sights', sub:'Higher visitor density, landmarks' },
  { id:'families', title:'Family-friendly', sub:'Services for kids, calmer micro-areas' },
  { id:'expats_international', title:'International / expat-friendly', sub:'International community, languages' },
  { id:'students', title:'Student vibe', sub:'Universities, student life' },
  { id:'young_professionals', title:'Young professionals', sub:'After-work vibe, convenience' },
  { id:'older_quiet', title:'Older / quiet vibe', sub:'Calmer pace, residential feel' },
  { id:'green_parks', title:'Parks & green areas', sub:'Parks, nature, playgrounds' },
  { id:'residential_quiet', title:'Residential & quiet', sub:'Lower noise, calmer streets' },
  { id:'urban_dense', title:'Urban & dense', sub:'City feel, dense blocks' },
  { id:'houses_more', title:'More houses', sub:'Higher share of houses, gardens' },
  { id:'apartments_more', title:'More apartments', sub:'Higher share of apartments' },
  { id:'premium_feel', title:'Premium feel', sub:'Higher-end housing & services' },
  { id:'value_for_money', title:'Value for money', sub:'More space/price balance (micro-area dependent)' },
  { id:'mixed_vibes', title:'Mixed vibes', sub:'Micro-areas vary a lot' },
  { id:'central_access', title:'Central access', sub:'Easy access to city centre' },
  { id:'eu_quarter_access', title:'EU quarter access', sub:'Convenient to EU institutions area' },
  { id:'train_hubs_access', title:'Train hubs access', sub:'Good access to major stations' },
  { id:'airport_access', title:'Airport access', sub:'Convenient access to Brussels Airport' },
  { id:'metro_strong', title:'Metro connectivity', sub:'Strong metro access' },
  { id:'tram_strong', title:'Tram connectivity', sub:'Strong tram access' },
  { id:'bike_friendly', title:'Bike-friendly', sub:'Comfortable cycling options' },
  { id:'car_friendly', title:'Car-friendly', sub:'Easier parking/driving (relative)' },
  { id:'night_caution', title:'Night caution', sub:'Some streets feel less comfortable late' },
  { id:'busy_traffic_noise', title:'Traffic & noise', sub:'Busy roads / higher noise near arteries' },
  { id:'schools_strong', title:'Schools access', sub:'Higher density of schools nearby' },
  { id:'childcare_strong', title:'Childcare access', sub:'Higher density of childcare & preschools' }
]

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
