import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'

const QuizContext = createContext(null)

const DEFAULT = {
  city: '',
  householdType: '', // solo | couple | family
  childrenCount: 0,
  childrenAges: [],
  mode: 'buy', // buy | rent
  bedrooms: '', // studio|1|2|3
  propertyType: '', // apartment|house|not_sure
  budgetMin: null,
  budgetMax: null,
  priorities: [],

  includeWorkCommute: null, // true|false|null
  workTransport: '',
  workMinutes: 30,
  workAddress: '',

  includeSchoolCommute: null,
  schoolTransport: '',
  schoolMinutes: 20
}

function load() {
  if (typeof window === 'undefined') return DEFAULT
  try {
    const raw = window.localStorage.getItem('rb_state_v2')
    if (!raw) return DEFAULT
    return { ...DEFAULT, ...JSON.parse(raw) }
  } catch {
    return DEFAULT
  }
}

export function QuizProvider({ children }) {
  const [state, setState] = useState(DEFAULT)

  useEffect(() => {
    setState(load())
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('rb_state_v2', JSON.stringify(state))
  }, [state])

  const value = useMemo(() => ({ state, setState }), [state])
  return <QuizContext.Provider value={value}>{children}</QuizContext.Provider>
}

export function useQuiz() {
  const ctx = useContext(QuizContext)
  if (!ctx) throw new Error('QuizProvider missing')
  return ctx
}

export function resetQuiz(setState) {
  setState(DEFAULT)
  if (typeof window !== 'undefined') window.localStorage.removeItem('rb_state_v2')
}
