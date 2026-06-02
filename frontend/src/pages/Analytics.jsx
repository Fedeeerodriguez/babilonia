import { useEffect, useMemo, useState } from 'react'
import { Search, X, BarChart3, Clock, Users, Wrench, MessagesSquare } from 'lucide-react'
import api from '../utils/api'

const fmtNum = (n) => (n ?? 0).toLocaleString('es-AR')
const fmtMs  = (n) => (n == null ? '—' : `${Math.round(n)} ms`)
const fmtDate = (d) => d ? new Date(d).toLocaleString('es-AR') : '—'

const RANGOS = [
  { id: '24h', label: '24h', days: 1 },
  { id: '7d',  label: '7 días', days: 7 },
  { id: '30d', label: '30 días', days: 30 },
  { id: '90d', label: '90 días', days: 90 },
]

export default function Analytics() {
  const [rango, setRango] = useState('7d')
  const [summary, setSummary] = useState(null)
  const [series, setSeries] = useState([])
  const [users, setUsers] = useState([])
  const [tools, setTools] = useState([])
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState('')
  const [active, setActive] = useState(null)
  const [loading, setLoading] = useState(true)

  const params = useMemo(() => {
    const r = RANGOS.find(x => x.id === rango)
    const to = new Date()
    const from = new Date(to.getTime() - r.days * 24 * 3600 * 1000)
    return { from: from.toISOString(), to: to.toISOString() }
  }, [rango])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.get('/api/analytics/summary',    { params }),
      api.get('/api/analytics/timeseries', { params: { ...params, bucket: rango === '24h' ? 'hour' : 'day' } }),
      api.get('/api/analytics/top-users',  { params }),
      api.get('/api/analytics/top-tools',  { params }),
    ]).then(([s, t, u, w]) => {
      setSummary(s.data); setSeries(t.data); setUsers(u.data); setTools(w.data)
    }).catch(()=>{}).finally(()=>setLoading(false))
  }, [rango])

  useEffect(() => {
    const tt = setTimeout(() => {
      api.get('/api/analytics/conversaciones', { params: { ...params, q: q || undefined, limit: 50 } })
        .then(r => { setItems(r.data.items || []); setTotal(r.data.total || 0) })
        .catch(()=>{})
    }, 250)
    return () => clearTimeout(tt)
  }, [params, q])

  const openDetail = (it) => {
    api.get(`/api/analytics/conversacion/${it.id}`)
       .then(r => setActive(r.data))
       .catch(()=> setActive(it))
  }

  const maxBucket = Math.max(1, ...series.map(s => s.total))
  const disabled = summary && summary.enabled === false

  return (
    <div className="max-w-7xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Inteligencia</div>
      <div className="flex items-end justify-between mb-8">
        <h1 className="hero-title text-4xl text-deep">Analítica de Tomi</h1>
        <div className="flex gap-1 p-1 bg-bone-100 rounded-xl">
          {RANGOS.map(r => (
            <button key={r.id} onClick={()=>setRango(r.id)}
              className={`px-3 py-1.5 text-[12px] rounded-lg transition ${
                rango === r.id ? 'bg-deep text-bone shadow-soft' : 'text-deep/70 hover:bg-bone-200/60'
              }`}>{r.label}</button>
          ))}
        </div>
      </div>

      {disabled && (
        <div className="card p-6 mb-6 border-amber-200 bg-amber-50/60 text-amber-900 text-sm">
          La tabla <code>tomi_conversaciones</code> todavía no existe. Corré el SQL del setup en Supabase y volvé a entrar.
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Kpi icon={<MessagesSquare size={16}/>} label="Interacciones"   value={fmtNum(summary?.total)} />
        <Kpi icon={<Users size={16}/>}          label="Usuarios únicos" value={fmtNum(summary?.usuarios_unicos)} />
        <Kpi icon={<Clock size={16}/>}          label="Latencia prom."  value={fmtMs(summary?.latencia_promedio_ms)} />
        <Kpi icon={<BarChart3 size={16}/>}      label="Tokens totales"  value={fmtNum(summary?.tokens_totales)} />
      </div>

      {/* Serie temporal + tools */}
      <div className="grid lg:grid-cols-3 gap-4 mb-6">
        <div className="card p-5 lg:col-span-2 shadow-soft">
          <div className="section-label !mt-0 mb-3">Volumen</div>
          {series.length === 0 ? (
            <div className="text-muted text-sm py-10 text-center">Sin datos en el período</div>
          ) : (
            <div className="flex items-end gap-1 h-40">
              {series.map((s, i) => (
                <div key={i} className="flex-1 group relative flex flex-col items-center">
                  <div className="w-full bg-cobalt-100 hover:bg-cobalt rounded-t transition"
                       style={{ height: `${(s.total / maxBucket) * 100}%`, minHeight: 2 }}
                       title={`${fmtDate(s.bucket)} · ${s.total} interacciones`} />
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card p-5 shadow-soft">
          <div className="section-label !mt-0 mb-3 flex items-center gap-2"><Wrench size={13}/> Herramientas más usadas</div>
          {tools.length === 0 ? (
            <div className="text-muted text-sm">Sin datos</div>
          ) : (
            <ul className="space-y-2">
              {tools.slice(0, 8).map((t, i) => (
                <li key={i} className="flex items-center justify-between text-[13px]">
                  <span className="text-deep font-mono text-[11px]">{t.tool}</span>
                  <span className="text-muted">{t.uso}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Top usuarios */}
      <div className="card p-5 mb-6 shadow-soft">
        <div className="section-label !mt-0 mb-3">Top usuarios</div>
        {users.length === 0 ? (
          <div className="text-muted text-sm">Sin datos</div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {users.slice(0, 9).map(u => (
              <div key={u.user_id} className="flex items-center justify-between px-3 py-2 rounded-lg bg-bone-100/60">
                <div className="min-w-0">
                  <div className="text-deep text-[13px] truncate">{u.nombre || u.user_id}</div>
                  <div className="text-muted text-[11px] font-mono truncate">{u.user_id}</div>
                </div>
                <div className="text-right">
                  <div className="text-deep font-semibold text-[13px]">{u.interacciones}</div>
                  <div className="text-muted text-[10px]">{fmtDate(u.ultima)}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tabla de conversaciones */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-display text-xl text-deep">Respuestas ({fmtNum(total)})</h2>
        <div className="relative max-w-md w-full">
          <Search size={15} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted"/>
          <input className="input pl-10" placeholder="Buscar en mensajes y respuestas..." value={q} onChange={e=>setQ(e.target.value)} />
        </div>
      </div>

      <div className="card overflow-hidden shadow-soft">
        <table className="w-full text-sm">
          <thead className="bg-bone-100/70 text-[11px] uppercase tracking-[0.14em] text-muted">
            <tr>
              <th className="text-left px-5 py-3">Cuándo</th>
              <th className="text-left px-5 py-3">Usuario</th>
              <th className="text-left px-5 py-3">Pregunta</th>
              <th className="text-left px-5 py-3">Respuesta</th>
              <th className="text-right px-5 py-3">Latencia</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={5} className="px-5 py-10 text-center text-muted">Cargando…</td></tr>}
            {!loading && items.map(it => (
              <tr key={it.id} onClick={()=>openDetail(it)}
                  className="border-t border-border/60 hover:bg-bone-100/50 cursor-pointer transition">
                <td className="px-5 py-3 text-muted text-[12px] whitespace-nowrap">{fmtDate(it.created_at)}</td>
                <td className="px-5 py-3">
                  <div className="text-deep text-[13px] truncate max-w-[18ch]">{it.user_nombre || '—'}</div>
                  <div className="text-muted text-[11px] font-mono truncate max-w-[18ch]">{it.user_id}</div>
                </td>
                <td className="px-5 py-3 text-deep truncate max-w-[26ch]">{it.mensaje_usuario}</td>
                <td className="px-5 py-3 text-muted truncate max-w-[36ch]">{it.respuesta_tomi}</td>
                <td className="px-5 py-3 text-right text-muted text-[12px] whitespace-nowrap">{fmtMs(it.latencia_ms)}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={5} className="px-5 py-12 text-center text-muted">Sin resultados</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {active && (
        <div className="fixed inset-0 z-50 bg-deep/30 backdrop-blur-sm flex justify-end" onClick={()=>setActive(null)}>
          <div className="w-full max-w-2xl bg-white h-full overflow-y-auto p-8 animate-slide-up" onClick={e=>e.stopPropagation()}>
            <div className="flex items-start justify-between mb-6">
              <div>
                <div className="hero-eyebrow">Interacción</div>
                <h2 className="font-display text-2xl font-semibold text-deep">{active.user_nombre || active.user_id}</h2>
                <div className="text-muted text-[12px] font-mono">{active.user_id} · {active.canal || 'canal n/d'}</div>
                <div className="text-muted text-[12px]">{fmtDate(active.created_at)}</div>
              </div>
              <button onClick={()=>setActive(null)} className="p-2 rounded-full hover:bg-bone-200/70"><X size={16}/></button>
            </div>

            <Section title="Mensaje del usuario">
              <div className="bg-bone-100 rounded-xl p-4 text-[13px] whitespace-pre-wrap text-deep">{active.mensaje_usuario || '—'}</div>
            </Section>

            <Section title="Respuesta de Tomi">
              <div className="bg-cobalt-50 border border-cobalt-200 rounded-xl p-4 text-[13px] whitespace-pre-wrap text-cobalt-800">{active.respuesta_tomi || '—'}</div>
            </Section>

            <div className="grid grid-cols-3 gap-3 mb-5">
              <Mini label="Latencia" v={fmtMs(active.latencia_ms)} />
              <Mini label="Tokens in"  v={fmtNum(active.tokens_input)} />
              <Mini label="Tokens out" v={fmtNum(active.tokens_output)} />
            </div>

            {Array.isArray(active.herramientas_usadas) && active.herramientas_usadas.length > 0 && (
              <Section title="Herramientas">
                <div className="flex flex-wrap gap-2">
                  {active.herramientas_usadas.map((t, i) => (
                    <span key={i} className="px-2 py-1 rounded-md bg-bone-100 text-deep text-[11px] font-mono">{t}</span>
                  ))}
                </div>
              </Section>
            )}

            {active.metadata && (
              <Section title="Metadata">
                <pre className="bg-bone-100 rounded-xl p-4 text-[11px] overflow-x-auto">{JSON.stringify(active.metadata, null, 2)}</pre>
              </Section>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Kpi({ icon, label, value }) {
  return (
    <div className="card p-5 shadow-soft">
      <div className="flex items-center gap-2 text-muted text-[11px] uppercase tracking-[0.14em] mb-2">
        {icon}{label}
      </div>
      <div className="font-display text-2xl text-deep">{value}</div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="mb-5">
      <div className="section-label !mt-0 mb-2">{title}</div>
      {children}
    </div>
  )
}

function Mini({ label, v }) {
  return (
    <div className="rounded-xl bg-bone-100/70 p-3">
      <div className="text-muted text-[10px] uppercase tracking-[0.14em]">{label}</div>
      <div className="text-deep font-display text-lg">{v}</div>
    </div>
  )
}
