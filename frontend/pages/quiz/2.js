import React from 'react'
import { useRouter } from 'next/router'
import Layout from '../../components/Layout'
import { useQuiz, resetQuiz } from '../../components/quizState'

function Choice({title, sub, selected, onClick}){
  return (
    <div className={selected ? 'choice selected' : 'choice'} onClick={onClick} role="button" tabIndex={0}>
      <p className="choiceTitle">{title}</p>
      <p className="choiceSub">{sub}</p>
    </div>
  )
}

export default function Step2(){
  const router = useRouter()
  const { state, setState } = useQuiz()

  const setType = (t) => {
    setState(s => {
      const next = { ...s, householdType: t }
      if (t !== 'family') {
        next.childrenCount = 0
        next.childrenAges = []
      } else if (!next.childrenCount) {
        next.childrenCount = 1
        next.childrenAges = ['']
      }
      return next
    })
  }

  const agesOk = state.householdType !== 'family'
    ? true
    : (state.childrenCount > 0 && (state.childrenAges || []).length === state.childrenCount && state.childrenAges.every(a => String(a).trim().length>0))

  const can = Boolean(state.householdType) && agesOk

  const setChildrenCount = (n) => {
    setState(s => {
      const ages = Array.from({length:n}, (_,i)=> (s.childrenAges && s.childrenAges[i]) ? s.childrenAges[i] : '')
      return { ...s, childrenCount:n, childrenAges:ages }
    })
  }

  const setAge = (idx, val) => {
    setState(s => {
      const ages = [...(s.childrenAges || [])]
      ages[idx] = val
      return { ...s, childrenAges: ages }
    })
  }

  return (
    <Layout
      step={2}
      title="Who is relocating?"
      subtitle="Select solo, couple, or family. If family, add children ages."
      actions={
        <div className="btnRow">
          <div className="btnLeft">
            <button className="linkBtn" onClick={() => router.push('/quiz/1')}>Back</button>
            <button className="linkBtn" onClick={() => { resetQuiz(setState); router.push('/quiz/1'); }}>Reset</button>
          </div>
          <button className="btn" disabled={!can} onClick={() => router.push('/quiz/3')}>Continue</button>
        </div>
      }
    >
      <div className="row">
        <Choice title="Solo" sub="One person relocating" selected={state.householdType==='solo'} onClick={()=>setType('solo')} />
        <Choice title="Couple" sub="Two adults relocating" selected={state.householdType==='couple'} onClick={()=>setType('couple')} />
        <Choice title="Family" sub="Adults + children" selected={state.householdType==='family'} onClick={()=>setType('family')} />
      </div>

      {state.householdType === 'family' ? (
        <>
          <div className="divider" />
          <div className="row" style={{alignItems:'center'}}>
            <div className="col">
              <p className="small">Number of children</p>
              <select className="input" value={state.childrenCount} onChange={(e)=>setChildrenCount(parseInt(e.target.value,10))}>
                {[1,2,3,4,5].map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          </div>

          <div style={{height:10}} />
          <div className="row">
            {Array.from({length: state.childrenCount}, (_,i)=>(
              <div className="col" key={i}>
                <p className="small">Child {i+1} age</p>
                <input className="input" placeholder="e.g., 3" value={(state.childrenAges||[])[i] || ''} onChange={(e)=>setAge(i, e.target.value)} />
              </div>
            ))}
          </div>
        </>
      ) : null}
    </Layout>
  )
}
