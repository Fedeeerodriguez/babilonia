import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import api from '../utils/api'

const fmtSec = (s) => s == null ? '—' : s < 60 ? `${s.toFixed(0)}s` : s < 3600 ? `${(s/60).toFixed(1)}m` : `${(s/3600).toFixed(1)}h`

export default function Dashboard() {
  const [summary, setSummary] = useState(null)
  const [series, setSeries] = useState([])
  const [days, setDays] = useState(7)

  useEffect(() => {
    const to = new Date()
    const from = new Date(Date.now() - days * 86400000)
    api.get('/api/metrics/summary', { params: { from: from.toISOString(), to: to.toISOString() } })
       .then(r => setSummary(r.data)).catch(()=>{})
    api.get('/api/metrics/timeseries', { params: { from: from.toISOString(), to: to.toISOString(), bucket: 'day' } })
       .then(r => setSeries(r.data.map(d => ({ ...d, day: new Date(d.bucket).toLocaleDateString('es-AR', { month:'short', day:'numeric' }) }))))
       .catch(()=>{})
  }, [days])

  return (
    <div className="max-w-7xl mx-auto animate-fade-in">
      <div className="flex items-end justify-between mb-10">
        <div>
          <div className="hero-eyebrow">Panel</div>
          <h1 className="hero-title text-5xl text-deep">Métricas Tomi</h1>
          <p className="text-muted mt-2 font-light">Soporte automático para asesores Allianz vía WATI.</p>
        </div>
        <div className="flex gap-2">
          {[1, 7, 30].map(d => (
            <button key={d} onClick={()=>setDays(d)}
              className={`px-3 py-1.5 rounded-full text-[12px] font-medium tracking-tight transition ${days===d?'bg-deep text-bone':'bg-bone-200/60 text-deep/70 hover:bg-bone-300'}`}>
              {d === 1 ? '24h' : `${d}d`}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5 mb-10">
        <KPI label="Tiempo respuesta promedio" value={fmtSec(summary?.avg_response_seconds)} accent />
        <KPI label="Mensajes enviados" value={summary?.sent ?? '—'} />
        <KPI label="Mensajes recibidos" value={summary?.received ?? '—'} />
        <KPI label="Respuestas asesor" value={summary?.advisor_replies ?? '—'} />
      </div>

      <div className="card p-6 shadow-soft">
        <div className="flex items-baseline justify-between mb-6">
          <h3 className="font-display text-xl font-semibold text-deep">Volumen por día</h3>
          <span className="text-[11px] uppercase tracking-[0.14em] text-muted">últimos {days} {days===1?'día':'días'}</span>
        </div>
        <div className="h-72">
          <ResponsiveContainer>
            <LineChart data={series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E0D6" />
              <XAxis dataKey="day" stroke="#6B7280" fontSize={11} />
              <YAxis stroke="#6B7280" fontSize={11} />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #E5E0D6', background: '#fff' }} />
              <Line type="monotone" dataKey="received" stroke="#2D76B2" strokeWidth={2} name="Recibidos" />
              <Line type="monotone" dataKey="advisor_replies" stroke="#2E3A5F" strokeWidth={2} name="Asesor" />
              <Line type="monotone" dataKey="bot_replies" stroke="#85B3D5" strokeWidth={2} name="Bot/Templates" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

function KPI({ label, value, accent }) {
  return (
    <div className="card p-6 card-hover shadow-soft">
      <div className="stat-label">{label}</div>
      <div className={`stat-value text-4xl mt-3 ${accent ? 'text-cobalt-700' : ''}`}>{value}</div>
    </div>
  )
}
