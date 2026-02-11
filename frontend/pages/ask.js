import React, { useEffect, useMemo, useRef, useState } from 'react'
import QuizLayout from '../components/QuizLayout'
import { useRouter } from 'next/router'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const API = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000'

function slugify(text){
  return (text || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '') || 'section'
}

function HighlightableMarkdown({ markdown, jumpTo, onReady }){
  const containerRef = useRef(null)

  useEffect(()=>{
    if(onReady) onReady()
  }, [onReady])

  useEffect(()=>{
    if(!jumpTo) return
    const el = document.getElementById(jumpTo)
    if(el){
      el.scrollIntoView({ behavior:'smooth', block:'start' })
      el.classList.add('hlFlash')
      setTimeout(()=>el.classList.remove('hlFlash'), 1400)
    }
  }, [jumpTo])

  const components = useMemo(()=>({
    h2: ({node, ...props}) => {
      const txt = String(props.children?.[0] || '').trim() || 'Section'
      const id = slugify(txt)
      return <h2 id={id} {...props} />
    },
    h3: ({node, ...props}) => {
      const txt = String(props.children?.[0] || '').trim() || 'Section'
      const id = slugify(txt)
      return <h3 id={id} {...props} />
    },
    h4: ({node, ...props}) => {
      const txt = String(props.children?.[0] || '').trim() || 'Section'
      const id = slugify(txt)
      return <h4 id={id} {...props} />
    },
  }), [])

  return (
    <div ref={containerRef} className="mdViewer">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown || ''}
      </ReactMarkdown>
    </div>
  )
}

export default function Ask(){
  const router = useRouter()
  const briefId = (router.query.brief_id || '').toString()

  const [md, setMd] = useState('')
  const [mdErr, setMdErr] = useState('')
  const [loadingMd, setLoadingMd] = useState(false)

  const [messages, setMessages] = useState([
    { role:'assistant', text:'Ask me anything about your report. I will answer using the report (Report-only) or verified official sources (Verified mode).', meta:null }
  ])
  const [q, setQ] = useState('')
  const [sending, setSending] = useState(false)

  const [mode, setMode] = useState('report_only') // report_only | verified
  const [jumpTo, setJumpTo] = useState('')

  const suggested = [
    'Why were these communes recommended?',
    'Explain the Family score for the top commune',
    'What should I verify during viewings?',
    'Explain Budget fit and trade-offs',
    'What are the main watch-outs for the top pick?'
  ]

  useEffect(()=>{
    if(!briefId) return
    let cancelled=false
    async function load(){
      setLoadingMd(true); setMdErr('')
      try{
        const res = await fetch(API + `/brief/download?brief_id=${encodeURIComponent(briefId)}&format=md`)
        if(!res.ok){
          const t = await res.text()
          throw new Error(t || 'Failed to load report markdown')
        }
        const t = await res.text()
        if(cancelled) return
        setMd(t)
        setLoadingMd(false)
      }catch(e){
        if(cancelled) return
        setMdErr(String(e.message || e))
        setLoadingMd(false)
      }
    }
    load()
    return ()=>{cancelled=true}
  }, [briefId])

  const download = (fmt) => {
    if(!briefId) return
    window.open(API + `/brief/download?brief_id=${encodeURIComponent(briefId)}&format=${encodeURIComponent(fmt)}`, '_blank')
  }

  const send = async (questionText) => {
    const question = (questionText ?? q).trim()
    if(!question || !briefId) return

    setMessages(ms => [...ms, { role:'user', text: question, meta:null }])
    setQ('')
    setSending(true)

    try{
      const res = await fetch(API + '/brief/qa', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ brief_id: briefId, question, mode })
      })
      if(!res.ok){
        const t = await res.text()
        throw new Error(t || 'Failed to answer')
      }
      const data = await res.json()
      const answer = data.answer || 'No answer'
      const meta = { citations: data.citations || [], confidence: data.confidence, mode: data.mode || mode }
      setMessages(ms => [...ms, { role:'assistant', text: answer, meta }])
      setSending(false)
    }catch(e){
      setMessages(ms => [...ms, { role:'assistant', text: `Error: ${String(e.message || e)}`, meta:null }])
      setSending(false)
    }
  }

  const onCitationClick = (c) => {
    if(c?.anchor){
      setJumpTo(c.anchor)
      return
    }
    if(c?.url){
      window.open(c.url, '_blank')
    }
  }

  const modeLabel = mode === 'verified' ? 'Verified lookup' : 'Report-only'
  const modeHint = mode === 'verified'
    ? 'Verified lookup uses allowlisted official domains and cites sources. Requires TAVILY_API_KEY on backend.'
    : 'Report-only answers strictly from your report (markdown + scores).'

  return (
    <QuizLayout
      step="Ask more"
      title="Ask more"
      subtitle="Chat with your report (with sources)"
      actions={
        <>
          <button className="linkBtn" onClick={()=>router.push('/report')}>Back to download</button>
          <button className="btn" disabled={!briefId} onClick={()=>download('pdf')}>Download PDF</button>
          <button className="btn" disabled={!briefId} onClick={()=>download('md')}>Download Markdown</button>
        </>
      }
    >
      {!briefId ? (
        <div className="noteBox" style={{borderColor:'var(--danger)', color:'var(--danger)'}}>
          Missing brief_id. Please go back to the report page.
        </div>
      ) : null}

      <div className="askShell">
        <div className="chatPane">
          <div className="noteBox" style={{marginBottom:12}}>
            <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:12, flexWrap:'wrap'}}>
              <div>
                <div className="small" style={{marginBottom:4}}>Mode: <b>{modeLabel}</b></div>
                <div className="small" style={{color:'var(--muted)'}}>{modeHint}</div>
              </div>
              <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
                <button
                  className={mode==='report_only' ? 'chip chipActive' : 'chip'}
                  onClick={()=>setMode('report_only')}
                >
                  Report-only
                </button>
                <button
                  className={mode==='verified' ? 'chip chipActive' : 'chip'}
                  onClick={()=>setMode('verified')}
                >
                  Verified lookup
                </button>
              </div>
            </div>
          </div>

          <div className="suggestRow">
            {suggested.map((s)=>(
              <button key={s} className="sug" disabled={sending} onClick={()=>send(s)}>{s}</button>
            ))}
          </div>

          <div className="chatBox">
            {messages.map((m, idx)=>(
              <div key={idx} className={m.role === 'user' ? 'msg msgUser' : 'msg msgBot'}>
                <div className="msgText">{m.text}</div>

                {m.role === 'assistant' && m.meta?.citations?.length ? (
                  <div className="msgMeta">
                    <div className="metaRow">
                      <span className="metaLabel">Sources:</span>
                      <div className="metaItems">
                        {m.meta.citations.map((c, i)=>(
                          <button key={i} className="cite" onClick={()=>onCitationClick(c)} title={c.anchor ? 'Jump to section' : (c.url ? 'Open source' : '')}>
                            {c.label || (c.url ? 'Official source' : 'Source')}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="metaRow">
                      <span className="metaLabel">Confidence:</span>
                      <span className="small">{typeof m.meta.confidence === 'number' ? m.meta.confidence.toFixed(2) : '—'}</span>
                      <span className="small" style={{marginLeft:10, color:'var(--muted)'}}>({m.meta.mode})</span>
                    </div>
                    {/* Optional: show quotes/snippets */}
                    {m.meta.citations.some(x=>x.quote || x.snippet) ? (
                      <div className="metaQuotes">
                        {m.meta.citations.slice(0,3).map((c, i)=>(
                          c.quote || c.snippet ? (
                            <div key={i} className="quote">
                              <div className="small" style={{color:'var(--muted)'}}>{c.label}</div>
                              <div className="small">{c.quote || c.snippet}</div>
                            </div>
                          ) : null
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ))}
            {sending ? <div className="small" style={{color:'var(--muted)'}}>Thinking…</div> : null}
          </div>

          <div className="inputRow">
            <input
              className="input"
              placeholder="Ask a question…"
              value={q}
              onChange={(e)=>setQ(e.target.value)}
              onKeyDown={(e)=>{ if(e.key==='Enter') send() }}
              disabled={sending || !briefId}
            />
            <button className="btn" disabled={sending || !q.trim() || !briefId} onClick={()=>send()}>
              Send
            </button>
          </div>
        </div>

        <div className="viewerPane">
          <div className="viewerHeader">
            <div>
              <div className="small"><b>Report viewer</b></div>
              <div className="small" style={{color:'var(--muted)'}}>Click a source to jump and highlight the section.</div>
            </div>
          </div>

          {loadingMd ? <div className="noteBox">Loading report…</div> : null}
          {mdErr ? <div className="noteBox" style={{borderColor:'var(--danger)', color:'var(--danger)'}}>{mdErr}</div> : null}

          {!loadingMd && md ? (
            <HighlightableMarkdown markdown={md} jumpTo={jumpTo} />
          ) : null}
        </div>
      </div>
    </QuizLayout>
  )
}
