import React, { useEffect, useMemo, useState } from 'react'
import Layout from '../components/Layout'
import { useRouter } from 'next/router'
import { useQuiz } from '../components/quizState'

const API = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000'

export default function Report(){
  const router = useRouter()
  const { state } = useQuiz()

  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [briefId, setBriefId] = useState('')
  const [clarQs, setClarQs] = useState([])
  const [clarAns, setClarAns] = useState({})
  const [generating, setGenerating] = useState(false)

  // timing only (no preview)
  const [llmMs, setLlmMs] = useState(null)
  const [pdfMs, setPdfMs] = useState(null)
  const [totalMs, setTotalMs] = useState(null)

  const payload = useMemo(()=>state, [state])

  useEffect(()=>{
    let cancelled=false
    async function run(){
      setLoading(true); setErr('')
      try{
        const res = await fetch(API + '/brief/draft', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify(payload)
        })
        if(!res.ok){
          const t = await res.text()
          throw new Error(t || 'Failed to generate draft')
        }
        const j = await res.json()
        if(cancelled) return

        setBriefId(j.brief_id)
        setClarQs(j.clarifying_questions || [])

        setLlmMs(j.llm_ms ?? null)
        setPdfMs(j.pdf_render_ms ?? null)
        setTotalMs(j.total_ms ?? null)

        setLoading(false)
      }catch(e){
        if(cancelled) return
        setErr(String(e.message || e))
        setLoading(false)
      }
    }
    run()
    return ()=>{cancelled=true}
  }, [])

  const finalize = async () => {
    setGenerating(true); setErr('')
    try{
      const res = await fetch(API + '/brief/final', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ brief_id: briefId, clarifying_answers: clarAns })
      })
      if(!res.ok){
        const t = await res.text()
        throw new Error(t || 'Failed to finalize')
      }
      const j = await res.json()

      setClarQs(j.clarifying_questions || [])

      setLlmMs(j.llm_ms ?? null)
      setPdfMs(j.pdf_render_ms ?? null)
      setTotalMs(j.total_ms ?? null)

      setGenerating(false)
    }catch(e){
      setErr(String(e.message || e))
      setGenerating(false)
    }
  }

  const download = (fmt) => {
    window.open(API + `/brief/download?brief_id=${encodeURIComponent(briefId)}&format=${encodeURIComponent(fmt)}`, '_blank')
  }

  const timingText = () => {
    const parts = []
    if (typeof llmMs === 'number') parts.push(`LLM: ${llmMs} ms`)
    if (typeof pdfMs === 'number') parts.push(`PDF: ${pdfMs} ms`)
    if (typeof totalMs === 'number') parts.push(`Total: ${totalMs} ms`)
    return parts.join(' • ')
  }

  return (
    <Layout
      step={6}
      title="Your brief is ready"
      subtitle="Download a 1-page report. If we need clarifications, answer them (optional) and regenerate."
      actions={
        <div className="btnRow">
          <button className="linkBtn" onClick={() => router.push('/quiz/6')}>Back</button>
          <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
            <button className="btn" disabled={!briefId || loading} onClick={()=>download('pdf')}>Download PDF</button>
            <button className="btn" disabled={!briefId || loading} onClick={()=>download('md')}>Download Markdown</button>
          </div>
        </div>
      }
    >
      {loading ? <div className="noteBox">Generating draft (can take 10–60s)...</div> : null}
      {err ? <div className="noteBox" style={{borderColor:'var(--danger)', color:'var(--danger)'}}>{err}</div> : null}

      {!loading && briefId ? (
        <>
          <div className="noteBox">brief_id: {briefId}</div>

          {timingText() ? (
            <div className="noteBox">{timingText()}</div>
          ) : null}

          {clarQs && clarQs.length > 0 ? (
            <>
              <div className="divider" />
              <p className="p">Clarifying questions (optional)</p>
              <div style={{display:'flex', flexDirection:'column', gap:14}}>
                {clarQs.map((q)=>(
                  <div key={q} style={{display:'flex', flexDirection:'column', gap:6}}>
                    <p className="small">{q}</p>
                    <input
                      className="input"
                      placeholder="Your answer"
                      value={clarAns[q] || ''}
                      onChange={(e)=>setClarAns(a=>({...a, [q]: e.target.value}))}
                    />
                  </div>
                ))}
              </div>
              <div className="btnRow" style={{justifyContent:'flex-end'}}>
                <button className="btn" disabled={generating} onClick={finalize}>
                  {generating ? 'Updating...' : 'Update brief with answers'}
                </button>
              </div>
            </>
          ) : (
            <div className="noteBox">No clarifications needed.</div>
          )}
        </>
      ) : null}
    </Layout>
  )
}
