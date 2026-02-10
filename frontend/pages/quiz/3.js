import React, { useMemo } from 'react'
import { useRouter } from 'next/router'
import Layout from '../../components/Layout'
import { useQuiz, resetQuiz } from '../../components/quizState'

const BUY = { min: 150000, max: 1500000, step: 5000, label: 'EUR (purchase)' }
const RENT = { min: 700, max: 6000, step: 50, label: 'EUR/month (rent)' }

function Pill({text, selected, onClick}){
  return <div className={selected ? 'pill selected' : 'pill'} onClick={onClick} role="button" tabIndex={0}>{text}</div>
}

function Toggle({mode, setMode}){
  return (
    <div className="toggle">
      <div className={mode==='buy' ? 'toggleBtn active' : 'toggleBtn'} onClick={()=>setMode('buy')}>Buy</div>
      <div className={mode==='rent' ? 'toggleBtn active' : 'toggleBtn'} onClick={()=>setMode('rent')}>Rent</div>
    </div>
  )
}

export default function Step3(){
  const router = useRouter()
  const { state, setState } = useQuiz()

  const cfg = state.mode === 'rent' ? RENT : BUY

  const initBudgets = () => {
    // if empty, set defaults based on mode
    setState(s=>{
      const cfg2 = s.mode==='rent' ? RENT : BUY
      const min = s.budgetMin ?? Math.round((cfg2.min + (cfg2.max-cfg2.min)*0.25)/cfg2.step)*cfg2.step
      const max = s.budgetMax ?? Math.round((cfg2.min + (cfg2.max-cfg2.min)*0.55)/cfg2.step)*cfg2.step
      return {...s, budgetMin:min, budgetMax:max}
    })
  }

  React.useEffect(()=>{ initBudgets() }, [state.mode])

  const setMode = (m) => setState(s=>({...s, mode:m, budgetMin:null, budgetMax:null}))

  const minVal = state.budgetMin ?? cfg.min
  const maxVal = state.budgetMax ?? cfg.max

  const setMin = (v) => {
    const nv = Math.min(v, maxVal - cfg.step)
    setState(s=>({...s, budgetMin:nv}))
  }
  const setMax = (v) => {
    const nv = Math.max(v, minVal + cfg.step)
    setState(s=>({...s, budgetMax:nv}))
  }

  const can = Boolean(state.bedrooms) && Boolean(state.propertyType) && (state.budgetMin != null) && (state.budgetMax != null)

  const budgetText = useMemo(()=>{
    const fmt = (n)=> n.toLocaleString('en-US')
    return `${fmt(minVal)} — ${fmt(maxVal)}`
  }, [minVal, maxVal])

  return (
    <Layout
      step={3}
      title="Housing preferences"
      subtitle="Choose bedrooms, property type, and budget range. Default mode is Buy (switch to Rent if needed)."
      actions={
        <div className="btnRow">
          <div className="btnLeft">
            <button className="linkBtn" onClick={() => router.push('/quiz/2')}>Back</button>
            <button className="linkBtn" onClick={() => { resetQuiz(setState); router.push('/quiz/1'); }}>Reset</button>
          </div>
          <button className="btn" disabled={!can} onClick={() => router.push('/quiz/4')}>Continue</button>
        </div>
      }
    >
      <div className="row" style={{alignItems:'center', justifyContent:'space-between'}}>
        <div className="col">
          <p className="small">Mode</p>
          <Toggle mode={state.mode} setMode={setMode} />
        </div>
        <div className="col" />
      </div>

      <div className="divider" />

      <p className="small">Bedrooms</p>
      <div className="pills">
        <Pill text="Studio" selected={state.bedrooms==='studio'} onClick={()=>setState(s=>({...s, bedrooms:'studio'}))} />
        <Pill text="1+ room" selected={state.bedrooms==='1'} onClick={()=>setState(s=>({...s, bedrooms:'1'}))} />
        <Pill text="2+ rooms" selected={state.bedrooms==='2'} onClick={()=>setState(s=>({...s, bedrooms:'2'}))} />
        <Pill text="3+ rooms" selected={state.bedrooms==='3'} onClick={()=>setState(s=>({...s, bedrooms:'3'}))} />
      </div>

      <div style={{height:16}} />

      <p className="small">Property type</p>
      <div className="pills">
        <Pill text="Apartment" selected={state.propertyType==='apartment'} onClick={()=>setState(s=>({...s, propertyType:'apartment'}))} />
        <Pill text="House" selected={state.propertyType==='house'} onClick={()=>setState(s=>({...s, propertyType:'house'}))} />
        <Pill text="Not sure" selected={state.propertyType==='not_sure'} onClick={()=>setState(s=>({...s, propertyType:'not_sure'}))} />
      </div>

      <div style={{height:16}} />

      <p className="small">Budget range</p>
      <div className="rangeWrap">
        <div className="rangeLine">
          <span className="rangeVal">{budgetText}</span>
          <span className="small">{cfg.label}</span>
        </div>
        <input className="range" type="range" min={cfg.min} max={cfg.max} step={cfg.step} value={minVal} onChange={(e)=>setMin(parseInt(e.target.value,10))}/>
        <input className="range" type="range" min={cfg.min} max={cfg.max} step={cfg.step} value={maxVal} onChange={(e)=>setMax(parseInt(e.target.value,10))}/>
        <div className="small">Tip: adjust the minimum and maximum to match your comfort range.</div>
      </div>
    </Layout>
  )
}
