import { useEffect, useState } from 'react'
import api from '../utils/api'

export default function Advisors() {
  const [rows, setRows] = useState([])
  useEffect(() => { api.get('/api/metrics/by-advisor').then(r => setRows(r.data)).catch(()=>{}) }, [])

  const max = Math.max(1, ...rows.map(r => r.replies))
  return (
    <div className="max-w-5xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Equipo</div>
      <h1 className="hero-title text-4xl text-deep mb-8">Asesores</h1>

      <div className="card p-2 shadow-soft">
        {rows.map((r, i) => (
          <div key={i} className="px-4 py-3 border-b border-border/40 last:border-0 grid grid-cols-[1fr_2fr_auto] items-center gap-4">
            <div className="font-medium text-deep">{r.operator_name || '— sin asignar —'}</div>
            <div className="h-1.5 rounded-full bg-bone-200 overflow-hidden">
              <div className="h-full bg-cobalt rounded-full transition-all" style={{ width: `${(r.replies/max)*100}%` }} />
            </div>
            <div className="text-right text-[13px] text-muted tabular-nums">{r.replies} respuestas</div>
          </div>
        ))}
        {!rows.length && <div className="px-5 py-12 text-center text-muted">Sin datos en el período</div>}
      </div>
    </div>
  )
}
