import React from 'react'
import { useRouter } from 'next/router'
import Layout from './Layout'
import { resetQuiz, useQuiz } from './quizState'

/**
 * QuizLayout adds a Reset action on every quiz step (except the final report page).
 * Reset clears the quiz state and returns the user to step 1.
 */
export default function QuizLayout({ step, title, subtitle, children, actions }) {
  const router = useRouter()
  const { setState } = useQuiz()

  const onReset = () => {
    resetQuiz(setState)
    router.push('/quiz/1')
  }

  // Compose actions: keep existing buttons but always add Reset.
  const composedActions = (
    <div className="btnRow">
      <button className="linkBtn" onClick={onReset}>Reset</button>
      {actions}
    </div>
  )

  return (
    <Layout
      step={step}
      title={title}
      subtitle={subtitle}
      actions={composedActions}
    >
      {children}
    </Layout>
  )
}
