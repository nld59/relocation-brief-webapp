import React, { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import Layout from '../components/Layout'
import { ALL_TAGS } from '../components/tags'

const API = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000'

function nowId(){
  return Math.random().toString(36).slice(2, 10)
}

function normalizeCity(input){
  const s = (input || '').trim()
  if(!s) return ''
  // MVP: keep it simple; backend expects non-empty "city"
  // We'll standardize Brussels if user mentions it.
  const low = s.toLowerCase()
  if(low.includes('brussels')) return 'Brussels'
  return s
}

function clampInt(v, min, max){
  const n = parseInt(v, 10)
  if(Number.isNaN(n)) return null
  return Math.max(min, Math.min(max, n))
}

function tagLabel(id){
  const t = ALL_TAGS.find(x => x.id === id)
  return t ? t.title : id
}

export default function ChatPage(){
  const [sessionId] = useState(() => 'chat_' + nowId())
  const [messages, setMessages] = useState(() => ([
    { role:'assistant', text:"Hi! I'm your relocation broker. Let's build your brief in a few questions.\n\nWhere do you want to relocate (city)?" }
  ]))
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

  // ChatState mirrors the quiz payload fields 1:1
  const [state, setState] = useState({
    city: '',
    householdType: '',
    childrenCount: 0,
    childrenAges: [],
    mode: 'buy',
    bedrooms: '2',
    propertyType: 'apartment',
    budgetMin: null,
    budgetMax: null,
    priorities: [],
    includeWorkCommute: false,
    workTransport: 'public_transport',
    workMinutes: 35,
    workAddress: '',
    includeSchoolCommute: false,
    schoolTransport: 'walk',
    schoolMinutes: 10,
    qualityMode: 'fast',
  })

  const [step, setStep] = useState('city') // city -> household -> housing -> budget -> top3 -> extras -> work -> school -> generate/clarify -> done
  const [tagPick, setTagPick] = useState([])

  const [briefId, setBriefId] = useState('')
  const [clarifying, setClarifying] = useState([]) // [{id,question,type,options}]
  const [clarAnswers, setClarAnswers] = useState({})

  const bottomRef = useRef(null)
  useEffect(() => { bottomRef.current?.scrollIntoView({behavior:'smooth'}) }, [messages, busy, clarifying, briefId])

  const canSend = input.trim().length > 0 && !busy

  function push(role, text){
    setMessages(prev => [...prev, { role, text }])
  }

  function askNext(nextStep, assistantText){
    if(assistantText) push('assistant', assistantText)
    setStep(nextStep)
  }

  async function callDraft(payload){
    const res = await fetch(`${API}/brief/draft`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    })
    const data = await res.json().catch(() => ({}))
    if(!res.ok){
      const err = data?.detail || `Request failed (${res.status})`
      throw new Error(err)
    }
    return data
  }

  async function callFinal(brief_id, clarifying_answers){
    const res = await fetch(`${API}/brief/final`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ brief_id, clarifying_answers }),
    })
    const data = await res.json().catch(() => ({}))
    if(!res.ok){
      const err = data?.detail || `Request failed (${res.status})`
      throw new Error(err)
    }
    return data
  }

  async function generateBrief(){
    setBusy(true)
    try{
      push('assistant', 'Got it. Generating your brief…')
      const payload = { ...state }
      const data = await callDraft(payload)
      setBriefId(data.brief_id)
      if((data.clarifying_questions || []).length > 0){
        setClarifying(data.clarifying_questions)
        push('assistant', "Quick clarifications so I can be accurate:")
        setStep('clarify')
      }else{
        push('assistant', `Your brief is ready. You can download the PDF, and we can continue in Q&A mode.`)
        setStep('done')
      }
    }catch(e){
      push('assistant', `I couldn't generate the brief: ${e.message}`)
      setStep('generate')
    }finally{
      setBusy(false)
    }
  }

  async function finalizeWithClarifications(){
    setBusy(true)
    try{
      const missing = clarifying.filter(q => clarAnswers[q.id] === undefined || clarAnswers[q.id] === '')
      if(missing.length){
        push('assistant', 'Please answer all clarification questions above first.')
        setBusy(false)
        return
      }
      push('assistant', 'Thanks — updating your brief…')
      const data = await callFinal(briefId, clarAnswers)
      if((data.clarifying_questions || []).length > 0){
        // rare: second round
        setClarifying(data.clarifying_questions)
        setClarAnswers({})
        push('assistant', 'One more quick thing:')
        setStep('clarify')
      }else{
        setClarifying([])
        push('assistant', `All set. Your brief is ready. You can download the PDF, and we can continue in Q&A mode.`)
        setStep('done')
      }
    }catch(e){
      push('assistant', `I couldn't finalize the brief: ${e.message}`)
    }finally{
      setBusy(false)
    }
  }

  function onSend(){
    if(!canSend) return
    const text = input.trim()
    setInput('')
    push('user', text)

    // Deterministic flow: each user message updates state and moves to next step.
    if(step === 'city'){
      const city = normalizeCity(text)
      if(!city){
        push('assistant', 'Please tell me the city (e.g., Brussels).')
        return
      }
      setState(s => ({...s, city}))
      askNext('household', `Great. How many people are relocating?\n\nChoose one: Solo / Couple / Family`)
      return
    }

    if(step === 'household'){
      const low = text.toLowerCase()
      if(low.includes('solo') || low.includes('one') || low === '1'){
        setState(s => ({...s, householdType:'solo', childrenCount:0, childrenAges:[]}))
        askNext('housing', 'Got it. Rent or buy? (rent / buy)')
        return
      }
      if(low.includes('couple') || low.includes('2')){
        setState(s => ({...s, householdType:'couple', childrenCount:0, childrenAges:[]}))
        askNext('housing', 'Got it. Rent or buy? (rent / buy)')
        return
      }
      if(low.includes('family')){
        setState(s => ({...s, householdType:'family'}))
        askNext('kids', 'How many children, and what are their ages?\n\nExample: "2 kids, ages 3 and 7"')
        return
      }
      push('assistant', 'Please reply with: Solo / Couple / Family')
      return
    }

    if(step === 'kids'){
      // extract count and ages
      const nums = (text.match(/\d+/g) || []).map(n => parseInt(n,10)).filter(n => !Number.isNaN(n))
      const count = nums.length ? nums[0] : null
      const ages = nums.length > 1 ? nums.slice(1, 1 + Math.min(5, nums.length-1)) : []
      if(count === null){
        push('assistant', 'Please include the number of children. Example: "2 kids, ages 3 and 7".')
        return
      }
      setState(s => ({...s, childrenCount: count, childrenAges: ages}))
      askNext('housing', 'Thanks. Rent or buy? (rent / buy)')
      return
    }

    if(step === 'housing'){
      const low = text.toLowerCase()
      if(low.includes('rent')){
        setState(s => ({...s, mode:'rent'}))
      }else if(low.includes('buy') || low.includes('purchase')){
        setState(s => ({...s, mode:'buy'}))
      }else{
        push('assistant', 'Please reply: rent or buy')
        return
      }
      askNext('bedrooms', 'How many rooms/bedrooms do you need?\n\nChoose: studio / 1 / 2 / 3')
      return
    }

    if(step === 'bedrooms'){
      const low = text.toLowerCase().trim()
      const allowed = new Set(['studio','1','2','3'])
      if(!allowed.has(low)){
        push('assistant', 'Please choose one: studio / 1 / 2 / 3')
        return
      }
      setState(s => ({...s, bedrooms: low}))
      askNext('propertyType', 'Apartment or house? (apartment / house / not sure)')
      return
    }

    if(step === 'propertyType'){
      const low = text.toLowerCase()
      let val = ''
      if(low.includes('apartment')) val='apartment'
      else if(low.includes('house')) val='house'
      else if(low.includes('not') || low.includes('sure')) val='not_sure'
      if(!val){
        push('assistant', 'Please reply: apartment / house / not sure')
        return
      }
      setState(s => ({...s, propertyType: val}))
      askNext('budget', 'What is your budget range?\n\nExamples:\n- "2000-3000"\n- "700k to 900k"\n(We will interpret based on rent/buy.)')
      return
    }

    if(step === 'budget'){
      const nums = (text.match(/\d+/g) || []).map(n => parseInt(n,10)).filter(n => !Number.isNaN(n))
      if(nums.length < 2){
        push('assistant', 'Please give a range with two numbers, e.g., "2000-3000".')
        return
      }
      let min = nums[0], max = nums[1]
      if(max < min){ const t=min; min=max; max=t }
      setState(s => ({...s, budgetMin:min, budgetMax:max}))
      setTagPick([])
      askNext('top3', 'Now pick your TOP 3 priorities (reply with 3 numbers):\n' +
        ALL_TAGS.slice(0, 12).map((t,i)=>`${i+1}. ${t.title}`).join('\n') +
        '\n\n(We will add more options right after.)')
      return
    }

    if(step === 'top3'){
      const nums = (text.match(/\d+/g) || []).map(n => parseInt(n,10)).filter(n => n>=1 && n<=ALL_TAGS.length)
      const uniq = [...new Set(nums)].slice(0,3)
      if(uniq.length < 3){
        push('assistant', 'Please reply with 3 numbers (e.g., "1 5 9").')
        return
      }
      const picked = uniq.map(n => ALL_TAGS[n-1].id)
      setTagPick(picked)
      setState(s => ({...s, priorities: picked}))
      askNext('extras', 'Great. Add up to 4 more priorities (optional). Reply with numbers, or type "skip".\n' +
        ALL_TAGS.map((t,i)=>`${i+1}. ${t.title}`).join('\n'))
      return
    }

    if(step === 'extras'){
      const low = text.toLowerCase().trim()
      if(low === 'skip' || low === 'no' || low === 'none'){
        askNext('work', 'Do you want to optimize for commute to work? (yes/no)')
        return
      }
      const nums = (text.match(/\d+/g) || []).map(n => parseInt(n,10)).filter(n => n>=1 && n<=ALL_TAGS.length)
      const uniq = [...new Set(nums)].slice(0, 4)
      const extra = uniq.map(n => ALL_TAGS[n-1].id).filter(id => !tagPick.includes(id))
      const combined = [...tagPick, ...extra].slice(0, 7)
      setState(s => ({...s, priorities: combined}))
      askNext('work', 'Do you want to optimize for commute to work? (yes/no)')
      return
    }

    if(step === 'work'){
      const low = text.toLowerCase()
      if(low.startsWith('y')){
        setState(s => ({...s, includeWorkCommute:true}))
        askNext('workDetails', 'Ok. How will you commute (public_transport / car / bike) and what is your max minutes?\nExample: "public_transport 35"\nYou can also add destination like "Wavre".')
        return
      }
      if(low.startsWith('n')){
        setState(s => ({...s, includeWorkCommute:false, workAddress:''}))
        askNext('school', 'Do you want to optimize for commute to school? (yes/no)')
        return
      }
      push('assistant', 'Please reply: yes or no')
      return
    }

    if(step === 'workDetails'){
      const low = text.toLowerCase()
      let transport = 'public_transport'
      if(low.includes('car')) transport='car'
      else if(low.includes('bike')) transport='bike'
      const nums = (text.match(/\d+/g) || []).map(n => parseInt(n,10)).filter(n => !Number.isNaN(n))
      const minutes = nums.length ? clampInt(nums[0], 5, 120) : null
      // crude "address" extraction: keep trailing words after minutes/transport
      let addr = ''
      // take last word tokens if looks like a place
      const tokens = text.split(' ').map(s=>s.trim()).filter(Boolean)
      if(tokens.length){
        const maybe = tokens[tokens.length-1]
        if(!/^\d+$/.test(maybe) && maybe.length>2 && !['car','bike','public_transport','pt'].includes(maybe.toLowerCase())){
          addr = tokens.slice(-2).join(' ')
        }
      }
      if(minutes === null){
        push('assistant', 'Please include max minutes. Example: "public_transport 35".')
        return
      }
      setState(s => ({...s, workTransport: transport, workMinutes: minutes, workAddress: addr || s.workAddress}))
      askNext('school', 'Do you want to optimize for commute to school? (yes/no)')
      return
    }

    if(step === 'school'){
      const low = text.toLowerCase()
      if(low.startsWith('y')){
        setState(s => ({...s, includeSchoolCommute:true}))
        askNext('schoolDetails', 'Ok. How will you commute to school (walk / public_transport / car) and max minutes?\nExample: "walk 10"')
        return
      }
      if(low.startsWith('n')){
        setState(s => ({...s, includeSchoolCommute:false}))
        askNext('generate', 'Perfect. I have enough to generate your brief. Type "generate".')
        return
      }
      push('assistant', 'Please reply: yes or no')
      return
    }

    if(step === 'schoolDetails'){
      const low = text.toLowerCase()
      let transport = 'walk'
      if(low.includes('car')) transport='car'
      else if(low.includes('public')) transport='public_transport'
      const nums = (text.match(/\d+/g) || []).map(n => parseInt(n,10)).filter(n => !Number.isNaN(n))
      const minutes = nums.length ? clampInt(nums[0], 5, 120) : null
      if(minutes === null){
        push('assistant', 'Please include minutes. Example: "walk 10".')
        return
      }
      setState(s => ({...s, schoolTransport: transport, schoolMinutes: minutes}))
      askNext('generate', 'Perfect. I have enough to generate your brief. Type "generate".')
      return
    }

    if(step === 'generate'){
      if(text.toLowerCase().includes('gen')){
        generateBrief()
      }else{
        push('assistant', 'Type "generate" when you are ready.')
      }
      return
    }

    if(step === 'done'){
      push('assistant', 'Your brief is ready. Use the buttons below to download or continue Q&A.')
      return
    }
  }

  const selectedTags = useMemo(() => (state.priorities || []).map(tagLabel).join(', '), [state.priorities])

  return (
    <Layout>
      <div className="container">
        <div className="card" style={{maxWidth:900}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline'}}>
            <h1 className="h1" style={{marginBottom:6}}>Chat with a broker</h1>
            {/* ✅ FIX: Next Link must not wrap an <a> unless legacyBehavior is used */}
            <Link href="/" className="linkBtn">Home</Link>
          </div>
          <p className="p" style={{marginTop:0}}>
            One conversation. I’ll ask a few questions, generate your PDF brief, then you can keep asking.
          </p>

          <div style={{
            border:'1px solid var(--stroke)',
            borderRadius:16,
            padding:12,
            height:520,
            overflowY:'auto',
            background:'rgba(0,0,0,0.12)'
          }}>
            {messages.map((m, idx) => (
              <div key={idx} style={{
                display:'flex',
                justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
                margin:'8px 0'
              }}>
                <div style={{
                  maxWidth:'78%',
                  padding:'10px 12px',
                  borderRadius:14,
                  whiteSpace:'pre-wrap',
                  border:'1px solid var(--stroke)',
                  background: m.role === 'user' ? 'rgba(47,102,255,0.20)' : 'rgba(255,255,255,0.06)'
                }}>
                  {m.text}
                </div>
              </div>
            ))}

            {step === 'clarify' && clarifying.length > 0 && (
              <div style={{marginTop:10, padding:10, borderRadius:12, border:'1px solid var(--stroke)', background:'rgba(255,255,255,0.04)'}}>
                <div style={{fontWeight:700, marginBottom:8}}>Clarifying questions</div>
                {clarifying.map((q) => (
                  <div key={q.id} style={{marginBottom:10}}>
                    <div style={{marginBottom:6}}>{q.question}</div>
                    {q.type === 'single_choice' && (q.options || []).map((opt) => (
                      <label key={opt.value} style={{display:'block', margin:'4px 0'}}>
                        <input
                          type="radio"
                          name={q.id}
                          value={opt.value}
                          checked={String(clarAnswers[q.id] || '') === String(opt.value)}
                          onChange={() => setClarAnswers(a => ({...a, [q.id]: opt.value}))}
                        />{' '}
                        {opt.label}
                      </label>
                    ))}
                    {q.type !== 'single_choice' && (
                      <input
                        className="input"
                        placeholder="Type your answer"
                        value={clarAnswers[q.id] || ''}
                        onChange={(e) => setClarAnswers(a => ({...a, [q.id]: e.target.value}))}
                      />
                    )}
                  </div>
                ))}
                <button className="btn" disabled={busy} onClick={finalizeWithClarifications}>
                  Apply clarifications
                </button>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          <div className="row" style={{marginTop:12}}>
            <input
              className="input"
              placeholder={busy ? 'Working…' : 'Type your message…'}
              value={input}
              disabled={busy}
              onChange={(e)=>setInput(e.target.value)}
              onKeyDown={(e)=>{ if(e.key==='Enter') onSend() }}
            />
            <button className="btn" disabled={!canSend} onClick={onSend}>
              Send
            </button>
          </div>

          <div style={{marginTop:10, color:'var(--muted)', fontSize:13}}>
            <div><b>Current inputs:</b> {state.city || '—'} · {state.mode} · budget {state.budgetMin ?? '—'}–{state.budgetMax ?? '—'} · priorities: {selectedTags || '—'}</div>
          </div>

          {briefId && (
            <div style={{marginTop:14, display:'flex', gap:10, flexWrap:'wrap'}}>
              <a className="btn" href={`${API}/brief/download?brief_id=${briefId}&format=pdf`} target="_blank" rel="noreferrer">
                Download PDF
              </a>
              <a className="btn" href={`/ask?brief_id=${briefId}`}>
                Continue Q&A
              </a>
              <a className="btn" href={`${API}/brief/download?brief_id=${briefId}&format=md`} target="_blank" rel="noreferrer">
                Download MD
              </a>
              <a className="btn" href={`${API}/brief/download?brief_id=${briefId}&format=norm`} target="_blank" rel="noreferrer">
                Download norm.json
              </a>
            </div>
          )}

          <div style={{marginTop:12, color:'var(--muted)', fontSize:12}}>
            Tip: In Iteration 2 we’ll add “Why?” and “What-if” buttons right here in chat.
          </div>
        </div>
      </div>
    </Layout>
  )
}
