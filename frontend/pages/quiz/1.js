import React, { useMemo } from 'react'
import { useRouter } from 'next/router'
import Layout from '../../components/Layout'
import { useQuiz, resetQuiz } from '../../components/quizState'

export default function Step1(){
  const router = useRouter()
  const { state, setState } = useQuiz()

  // ✅ Пока доступен только один city pack
  // В будущем просто расширишь массив: ["Brussels, Belgium", "Barcelona, Spain", ...]
  const supportedLocations = useMemo(() => ([
    "Brussels, Belgium"
  ]), [])

  const cityRaw = (state.city || '').trim()

  // ✅ Continue активен только если введено ровно одно из поддерживаемых значений
  // (чтобы не было “любого названия”)
  const can = supportedLocations.some(x => x.toLowerCase() === cityRaw.toLowerCase())

  return (
    <Layout
      step={1}
      title="Which city/metro area are you relocating to?"
      subtitle="Start typing your city. Choose from the suggested list. Continue becomes active once a supported city is selected."
      actions={
        <div className="btnRow">
          <button className="linkBtn" onClick={() => { resetQuiz(setState); }}>Reset</button>
          <button className="btn" disabled={!can} onClick={() => router.push('/quiz/2')}>Continue</button>
        </div>
      }
    >
      <input
        className="input"
        placeholder="Your location (e.g., Brussels)"
        value={state.city}
        list="supported-locations"
        autoComplete="off"
        onChange={(e)=>setState(s=>({...s, city:e.target.value}))}
      />

      {/* ✅ Нативный “умный” dropdown (datalist) */}
      <datalist id="supported-locations">
        {supportedLocations.map(loc => (
          <option key={loc} value={loc} />
        ))}
      </datalist>

      {/* (опционально) лёгкая подсказка пользователю */}
      {!can && cityRaw.length > 0 && (
        <div style={{ marginTop: 10, opacity: 0.8, fontSize: 13 }}>
          Please select a supported city from the dropdown. Currently available: Brussels, Belgium.
        </div>
      )}
    </Layout>
  )
}
