import React from 'react'
import { useRouter } from 'next/router'
import Layout from '../../components/Layout'
import { useQuiz } from '../../components/quizState'

function Pill({text, selected, onClick}){
  return <div className={selected ? 'pill selected' : 'pill'} onClick={onClick} role="button" tabIndex={0}>{text}</div>
}

export default function Step6(){
  const router = useRouter()
  const { state, setState } = useQuiz()

  const include = state.includeSchoolCommute
  const can = include === false
    ? true
    : (include === true && Boolean(state.schoolTransport) && Number(state.schoolMinutes) > 0)

  const goNext = () => {
    if (include === false){
      setState(s=>({...s, schoolTransport:'', schoolMinutes:20}))
    }
    router.push('/report')
  }

  const familyHint = state.householdType === 'family' ? "Because you selected Family, you may want to include school commute — but it’s still optional." : "Optional — include only if relevant."

  return (
    <Layout
      step={6}
      title="Ideal commute to school (or other establishment)"
      subtitle={familyHint}
      actions={
        <div className="btnRow">
          <button className="linkBtn" onClick={() => router.push('/quiz/5')}>Back</button>
          <button className="btn" disabled={!can} onClick={goNext}>Continue</button>
        </div>
      }
    >
      <p className="small">Include school commute in the report?</p>
      <div className="pills">
        <Pill text="Yes" selected={include===true} onClick={()=>setState(s=>({...s, includeSchoolCommute:true}))} />
        <Pill text="Skip" selected={include===false} onClick={()=>setState(s=>({...s, includeSchoolCommute:false}))} />
      </div>

      {include === true ? (
        <>
          <div className="divider" />
          <p className="small">Transport</p>
          <div className="pills">
            <Pill text="Car" selected={state.schoolTransport==='car'} onClick={()=>setState(s=>({...s, schoolTransport:'car'}))} />
            <Pill text="Metro" selected={state.schoolTransport==='metro'} onClick={()=>setState(s=>({...s, schoolTransport:'metro'}))} />
            <Pill text="Walk" selected={state.schoolTransport==='walk'} onClick={()=>setState(s=>({...s, schoolTransport:'walk'}))} />
            <Pill text="Bike" selected={state.schoolTransport==='bike'} onClick={()=>setState(s=>({...s, schoolTransport:'bike'}))} />
          </div>

          <div style={{height:16}} />
          <p className="small">Max one-way time: <span className="rangeVal">{state.schoolMinutes} min</span></p>
          <input className="range" type="range" min={5} max={90} step={5} value={state.schoolMinutes} onChange={(e)=>setState(s=>({...s, schoolMinutes:parseInt(e.target.value,10)}))} />
        </>
      ) : null}

      {include === null ? (
        <div className="noteBox">Pick Yes or Skip to continue.</div>
      ) : null}
    </Layout>
  )
}
