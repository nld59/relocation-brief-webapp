import '../styles/globals.css'
import { QuizProvider } from '../components/quizState'

export default function App({ Component, pageProps }) {
  return (
    <QuizProvider>
      <Component {...pageProps} />
    </QuizProvider>
  )
}
