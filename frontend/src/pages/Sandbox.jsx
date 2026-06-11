import { useEffect, useState } from 'react'
import { ThumbsUp, ThumbsDown, Check, Sparkles, RefreshCw, Download } from 'lucide-react'
import api from '../utils/api'
import { useAuth } from '../context/AuthContext'

const TAGS = ['tono', 'dato_incorrecto', 'incompleta', 'no_entendio', 'fuera_de_tema', 'formato']
const STATUS_FILTERS = [
  { key: '', label: 'Todas' },
  { key: 'pending', label: 'Pendientes' },
  { key: 'reviewed', label: 'Revisadas' },
  { key: 'promoted', label: 'Promovidas' },
]

function StatCard({ label, value, accent }) {
  return (
    <div className="card p-5 shadow-soft">
      <div className="text-[11px] uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className={`text-3xl font-display font-semibold mt-1 ${accent || 'text-deep'}`}>{value}</div>
    </div>
  )
}

function FeedbackCard({ fb, onChanged, isAdmin }) {
  const [corregida, setCorregida] = useState(fb.respuesta_corregida || '')
  const [tags, setTags] = useState(fb.tags || [])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const toggleTag = (t) => setTags((cur) => cur.includes(t) ? cur.filter(x => x !== t) : [...cur, t])

  const review = async (rating) => {
    setBusy(true); setMsg('')
    try {
      await api.post(`/api/feedback/${fb.id}/review`, {
        rating,
        respuesta_corregida: corregida.trim() || null,
        tags,
      })
      onChanged()
    } catch (e) { setMsg(e.response?.data?.detail || 'Error') }
    finally { setBusy(false) }
  }

  const promote = async () => {
    setBusy(true); setMsg('')
    try {
      await api.post(`/api/feedback/${fb.id}/promote`)
      onChanged()
    } catch (e) { setMsg(e.response?.data?.detail || 'Error') }
    finally { setBusy(false) }
  }

  const badge = {
    pending: 'bg-amber-100 text-amber-700',
    reviewed: 'bg-cobalt-100 text-cobalt-700',
    promoted: 'bg-emerald-100 text-emerald-700',
  }[fb.status] || 'bg-bone-200 text-muted'

  return (
    <div className="card p-6 shadow-soft">
      <div className="flex items-center gap-2 mb-3 text-[11px]">
        <span className={`px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide ${badge}`}>{fb.status}</span>
        {fb.canal && <span className="chip-cobalt">{fb.canal}</span>}
        {fb.source && <span className="chip-cobalt">{fb.source}</span>}
        {fb.rating && (
          <span className={fb.rating === 'good' ? 'text-emerald-600' : 'text-rose-600'}>
            {fb.rating === 'good' ? '👍 good' : '👎 bad'}
          </span>
        )}
        <span className="ml-auto text-muted">{new Date(fb.created_at).toLocaleString('es-AR')}</span>
      </div>

      <div className="mb-3">
        <div className="label">Pregunta {fb.user_email ? `· ${fb.user_email}` : ''}</div>
        <div className="text-deep font-medium">{fb.pregunta}</div>
      </div>

      <div className="mb-4">
        <div className="label">Respuesta de Tomi</div>
        <div className="text-muted whitespace-pre-wrap text-[13px]">{fb.respuesta_tomi || <em>(sin respuesta)</em>}</div>
      </div>

      <div className="mb-3">
        <div className="label">Respuesta corregida (opcional)</div>
        <textarea
          className="input min-h-[80px]"
          placeholder="Escribí la respuesta como debería haber sido…"
          value={corregida}
          onChange={(e) => setCorregida(e.target.value)}
        />
      </div>

      <div className="mb-4">
        <div className="label">Etiquetas del problema</div>
        <div className="flex flex-wrap gap-2">
          {TAGS.map(t => (
            <button
              key={t}
              type="button"
              onClick={() => toggleTag(t)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition ${
                tags.includes(t) ? 'bg-deep text-bone' : 'bg-bone-200/60 text-muted hover:bg-bone-200'
              }`}
            >{t}</button>
          ))}
        </div>
      </div>

      {msg && <div className="mb-3 text-[12px] text-rose-600">{msg}</div>}

      <div className="flex flex-wrap gap-2">
        <button disabled={busy} onClick={() => review('good')} className="btn-ghost flex items-center gap-1.5">
          <ThumbsUp size={14} /> Aprobar
        </button>
        <button disabled={busy} onClick={() => review('bad')} className="btn-ghost flex items-center gap-1.5">
          <ThumbsDown size={14} /> Marcar mala
        </button>
        {isAdmin && fb.status !== 'promoted' && (
          <button disabled={busy} onClick={promote} className="btn-primary flex items-center gap-1.5 ml-auto">
            <Sparkles size={14} /> Enseñarle a Tomi
          </button>
        )}
        {fb.status === 'promoted' && (
          <span className="ml-auto flex items-center gap-1.5 text-emerald-600 text-[13px] font-medium">
            <Check size={15} /> Aprendido ({fb.promoted_doc_source})
          </span>
        )}
      </div>
    </div>
  )
}

export default function Sandbox() {
  const { isAdmin } = useAuth()
  const [items, setItems] = useState([])
  const [stats, setStats] = useState(null)
  const [status, setStatus] = useState('pending')
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    const params = status ? { status } : {}
    Promise.all([
      api.get('/api/feedback', { params }).then(r => setItems(r.data)).catch(() => setItems([])),
      api.get('/api/feedback/stats').then(r => setStats(r.data)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [status])

  const exportar = async () => {
    try {
      const r = await api.get('/api/feedback/export')
      const blob = new Blob([JSON.stringify(r.data.dataset, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'tomi_feedback_dataset.json'; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { /* noop */ }
  }

  return (
    <div className="max-w-5xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Sandbox</div>
      <h1 className="hero-title text-4xl text-deep mb-2">Entrenamiento de Tomi</h1>
      <p className="text-muted font-light mb-8">
        Revisá y corregí las respuestas de Tomi. Al aprobarlas, se cargan a su base de conocimiento y aprende.
      </p>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard label="Pendientes" value={stats.pendientes} accent="text-amber-600" />
          <StatCard label="Tasa de aprobación" value={`${Math.round(stats.tasa_aprobacion * 100)}%`} accent="text-emerald-600" />
          <StatCard label="Promovidas" value={stats.promovidas} accent="text-cobalt-700" />
          <StatCard label="Total" value={stats.total} />
        </div>
      )}

      <div className="flex items-center gap-2 mb-6">
        {STATUS_FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setStatus(f.key)}
            className={`px-3 py-1.5 rounded-full text-[12px] font-medium transition ${
              status === f.key ? 'bg-deep text-bone' : 'bg-bone-200/60 text-muted hover:bg-bone-200'
            }`}
          >{f.label}</button>
        ))}
        <button onClick={load} className="btn-ghost flex items-center gap-1.5 ml-auto"><RefreshCw size={14} /> Refrescar</button>
        {isAdmin && <button onClick={exportar} className="btn-ghost flex items-center gap-1.5"><Download size={14} /> Exportar dataset</button>}
      </div>

      <div className="space-y-5">
        {loading && <div className="text-muted text-center py-12">Cargando…</div>}
        {!loading && items.map(fb => (
          <FeedbackCard key={fb.id} fb={fb} onChanged={load} isAdmin={isAdmin} />
        ))}
        {!loading && !items.length && (
          <div className="card p-12 text-center text-muted shadow-soft">No hay interacciones en este estado.</div>
        )}
      </div>
    </div>
  )
}
