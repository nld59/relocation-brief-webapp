import React from 'react'
import Link from 'next/link'

export default function Home(){
  return (
    <div className="container">
      <div className="card">
        <h1 className="h1">Relocation Brief Builder</h1>
        <p className="p">Answer a short quiz and get a 1-page relocation brief (Top-3 areas + priorities + next steps).</p>
        <div className="btnRow" style={{justifyContent:'flex-start'}}>
          <Link href="/quiz/1"><button className="btn">Give me a detailed brief</button></Link>
        </div>
        <div className="noteBox">
          This is a product prototype (local). Landing design will be improved later.
        </div>
      </div>
    </div>
  )
}
