import React from 'react'

export default function Layout({ step, title, subtitle, children, actions }) {
  const dots = [1,2,3,4,5,6]
  return (
    <div className="container">
      <div className="card">
        <div className="dots" aria-label="progress">
          {dots.map(n => (
            <div key={n} className={n===step ? 'dot active' : 'dot'} />
          ))}
        </div>
        <div style={{height:16}} />
        <h1 className="h1">{title}</h1>
        {subtitle ? <p className="p">{subtitle}</p> : null}
        {children}
        {actions}
      </div>
    </div>
  )
}
