import React from 'react'
import { useRouter } from 'next/router'
import Layout from '../../components/Layout'
import { useQuiz } from '../../components/quizState'

function Pill({text, selected, onClick}){
  return <div className={selected ? 'pill selected' : 'pill'} onClick={onClick} role="button" tabIndex={0}>{text}</div>
}

export default function Step5(){
  const router = useRouter()
  const { state, setState } = useQuiz()

  const include = state.includeWorkCommute

  const can = include === false
    ? true
    : (include === true && Boolean(state.workTransport) && Number(state.workMinutes) > 0 && (state.workAddress||'').trim().length>0)

  const goNext = () => {
    // if user skipped, clear commute fields
    if (include === false){
      setState(s=>({...s, workTransport:'', workMinutes:30, workAddress:''}))
    }
    router.push('/quiz/6')
  }

  return (
    <Layout
      step={5}
      title="What’s your ideal commute to work?"
      subtitle="This step is optional. You can skip it if you work remotely or don’t care about commute."
      actions={
        <div className="btnRow">
          <button className="linkBtn" onClick={() => router.push('/quiz/4')}>Back</button>
          <button className="btn" disabled={!can} onClick={goNext}>Continue</button>
        </div>
      }
    >
      <p className="small">Include work commute in the report?</p>
      <div className="pills">
        <Pill text="Yes" selected={include===true} onClick={()=>setState(s=>({...s, includeWorkCommute:true}))} />
        <Pill text="Skip" selected={include===false} onClick={()=>setState(s=>({...s, includeWorkCommute:false}))} />
      </div>

      {include === true ? (
        <>
          <div className="divider" />
          <p className="small">Transport</p>
          <div className="pills">
            <Pill text="Car" selected={state.workTransport==='car'} onClick={()=>setState(s=>({...s, workTransport:'car'}))} />
            <Pill text="Walk" selected={state.workTransport==='walk'} onClick={()=>setState(s=>({...s, workTransport:'walk'}))} />
            <Pill text="Bike" selected={state.workTransport==='bike'} onClick={()=>setState(s=>({...s, workTransport:'bike'}))} />
          </div>

          <div style={{height:16}} />
          <p className="small">Max one-way time: <span className="rangeVal">{state.workMinutes} min</span></p>
          <input className="range" type="range" min={5} max={90} step={5} value={state.workMinutes} onChange={(e)=>setState(s=>({...s, workMinutes:parseInt(e.target.value,10)}))} />

          <div style={{height:16}} />
          <p className="small">Office area/address/company name</p>
          <input className="input" placeholder="e.g., European Quarter / Rue de la Loi / Company HQ" value={state.workAddress} onChange={(e)=>setState(s=>({...s, workAddress:e.target.value}))}/>
        </>
      ) : null}

      {include === null ? (
        <div className="noteBox">Pick Yes or Skip to continue.</div>
      ) : null}
    </Layout>
  )
}
