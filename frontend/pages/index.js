import React from 'react'
import Link from 'next/link'

export default function Home(){
  return (
    <div className="container">
      <div className="card">
        <h1 className="h1">Relocation Brief Builder</h1>
        <p className="p">Answer a short quiz and get a detailed relocation brief (Top-3 communes + microhood shortlist + next steps).</p>
        <div className="btnRow" style={{justifyContent:'flex-start'}}>
          <Link href="/quiz/1"><button className="btn">Give me a detailed brief</button></Link>
        </div>
        <div className="previewWrap">
          <div className="previewFrame" aria-label="Sample preview">
            {/* Sample screenshot: first page only */}
            <img className="previewImg" src="/preview-01.png" alt="Sample brief preview" />
            <div className="previewFade" />
          </div>
          <div className="small" style={{marginTop:10}}>
            Preview: first page sample (content will be customized to your answers).
          </div>
        </div>

        <div className="noteBox">
          This is a product prototype (local). Landing design will be improved later.
        </div>
      </div>
    </div>
  )
}
