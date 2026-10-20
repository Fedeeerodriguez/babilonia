import { useEffect, useState } from 'react'
import { Megaphone, Plus, Pencil, Trash2, Power, Eye, RefreshCw } from 'lucide-react'
import api from '../utils/api'

// Avisos temporales de Tommy: información que el equipo agrega y quita (ej. "la Liga Babilonia está
// cerrada por mantenimiento"). Los vigentes le llegan al agente en cada mensaje, con prioridad sobre
// lo demás que sabe. Se pueden programar con fecha de inicio y de fin.

const AUDIENCIAS = [
  ['todos', 'Todos'], ['asesor', 'Asesores'], ['cliente', 'Clientes'],
  ['estudiante', 'Estudiantes'], ['prospecto', 'Prospectos'],
]
const NOMBRE_AUD = Object.fromEntries(AUDIENCIAS)
const ESTADO = {
  vigente: ['Vigente', 'bg-emerald-100 text-emerald-700'],
  programado: ['Programado', 'bg-amber-100 text-amber-700'],
  apagado: ['Apagado', 'bg-bone-200 text-muted'],
  vencido: ['Vencido', 'bg-bone-200 text-muted'],
}
const VACIO = { titulo: '', contenido: '', audiencia: 'todos', activo: true, desde: '', hasta: '' }

// ISO (UTC) ↔ valor de <input type="datetime-local"> en la hora de esta computadora.
const aInput = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
const aIso = (v) => (v ? new Date(v).toISOString() : null)
const fecha = (iso) => iso
  ? new Date(iso).toLocaleString('es-MX', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  : null

function Formulario({ inicial, onGuardar, onCancelar, busy }) {
  const [f, setF] = useState(inicial)
  const set = (k) => (e) => setF(s => ({ ...s, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const listo = f.titulo.trim() && f.contenido.trim()

  return (
    <div className="card p-5 shadow-soft space-y-3">
      <label className="block">
        <span className="text-[11px] uppercase tracking-wider text-muted">Título</span>
        <input id="aviso-titulo" value={f.titulo} onChange={set('titulo')} maxLength={120}
          placeholder="Liga Babilonia en mantenimiento"
          className="w-full mt-1 text-sm border border-border rounded-lg px-3 py-2 bg-white/80" />
      </label>
      <label className="block">
        <span className="text-[11px] uppercase tracking-wider text-muted">Qué tiene que saber Tommy</span>
        <textarea id="aviso-contenido" value={f.contenido} onChange={set('contenido')} rows={4} maxLength={1500}
          placeholder="La Liga Babilonia está cerrada por mantenimiento. Vuelve a abrir el lunes 3 de noviembre. Si preguntan por puntos o retos, avisar que se actualizan al reabrir."
          className="w-full mt-1 text-sm border border-border rounded-lg px-3 py-2 bg-white/80" />
        <span className="text-[11px] text-muted">{f.contenido.length}/1500 · Escribilo como se lo explicarías a Tommy; él lo usa solo si viene al caso.</span>
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="block">
          <span className="text-[11px] uppercase tracking-wider text-muted">Para quién</span>
          <select id="aviso-audiencia" value={f.audiencia} onChange={set('audiencia')}
            className="w-full mt-1 text-sm border border-border rounded-lg px-3 py-2 bg-white/80">
            {AUDIENCIAS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-[11px] uppercase tracking-wider text-muted">Desde (opcional)</span>
          <input id="aviso-desde" type="datetime-local" value={f.desde} onChange={set('desde')}
            className="w-full mt-1 text-sm border border-border rounded-lg px-3 py-2 bg-white/80" />
        </label>
        <label className="block">
          <span className="text-[11px] uppercase tracking-wider text-muted">Hasta (opcional)</span>
          <input id="aviso-hasta" type="datetime-local" value={f.hasta} onChange={set('hasta')}
            className="w-full mt-1 text-sm border border-border rounded-lg px-3 py-2 bg-white/80" />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm text-deep">
        <input id="aviso-activo" type="checkbox" checked={f.activo} onChange={set('activo')} /> Prendido
      </label>
      <div className="flex gap-2">
        <button disabled={busy || !listo} onClick={() => onGuardar(f)} className="btn-primary text-sm px-4 py-2">Guardar</button>
        <button onClick={onCancelar} className="text-sm px-4 py-2 text-muted">Cancelar</button>
      </div>
    </div>
  )
}

export default function AvisosTomi() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState(null)
  const [editando, setEditando] = useState(null)   // null | 'nuevo' | id
  const [busy, setBusy] = useState(false)
  const [tipo, setTipo] = useState('cliente')
  const [preview, setPreview] = useState('')

  const load = () => {
    setLoading(true)
    api.get('/api/tomi/avisos')
      .then(r => setData(r.data))
      .catch(() => setMsg({ ok: false, text: 'No se pudieron cargar los avisos. ¿Sos admin?' }))
      .finally(() => setLoading(false))
    api.get('/api/tomi/avisos/vista-previa', { params: { tipo } })
      .then(r => setPreview(r.data.bloque || ''))
      .catch(() => setPreview(''))
  }
  useEffect(() => { load() }, [tipo]) // eslint-disable-line react-hooks/exhaustive-deps

  const guardar = async (f) => {
    setBusy(true); setMsg(null)
    const body = { ...f, desde: aIso(f.desde), hasta: aIso(f.hasta) }
    try {
      if (editando === 'nuevo') await api.post('/api/tomi/avisos', body)
      else await api.put(`/api/tomi/avisos/${editando}`, body)
      setMsg({ ok: true, text: 'Aviso guardado. Tommy lo usa desde el próximo mensaje.' })
      setEditando(null); load()
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'No se pudo guardar.' })
    } finally { setBusy(false) }
  }

  const alternar = async (a) => {
    setMsg(null)
    try {
      await api.put(`/api/tomi/avisos/${a.id}`, { activo: !a.activo })
      setMsg({ ok: true, text: a.activo ? 'Aviso apagado: Tommy ya no lo usa.' : 'Aviso prendido.' })
      load()
    } catch (err) { setMsg({ ok: false, text: err.response?.data?.detail || 'No se pudo cambiar.' }) }
  }

  const borrar = async (a) => {
    if (!window.confirm(`¿Borrar el aviso "${a.titulo}"? Si solo querés pausarlo, apagalo.`)) return
    try {
      await api.delete(`/api/tomi/avisos/${a.id}`)
      setMsg({ ok: true, text: 'Aviso borrado.' }); load()
    } catch (err) { setMsg({ ok: false, text: err.response?.data?.detail || 'No se pudo borrar.' }) }
  }

  const items = data?.items || []

  return (
    <div className="max-w-5xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Conocimiento de Tommy</div>
      <h1 className="hero-title text-4xl text-deep mb-2">Avisos temporales</h1>
      <p className="text-muted font-light mb-6">
        Información de temporada que Tommy tiene que saber por un tiempo: un cierre por mantenimiento, un cambio de
        horario, una promoción. Los avisos vigentes le llegan en cada mensaje y tienen prioridad sobre lo que ya sabe.
        Cuando dejan de aplicar, apagalos o poneles fecha de fin.
      </p>

      {msg && (
        <div className={`mb-4 text-sm px-4 py-2 rounded-lg ${msg.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
          {msg.text}
        </div>
      )}

      <div className="flex items-center gap-3 mb-4">
        {editando === null && (
          <button onClick={() => setEditando('nuevo')} className="btn-primary text-sm px-4 py-2 flex items-center gap-1.5">
            <Plus size={15} /> Nuevo aviso
          </button>
        )}
        <button onClick={load} className="text-sm text-cobalt-700 flex items-center gap-1.5"><RefreshCw size={14} /> Recargar</button>
        {data && <span className="text-sm text-muted">{data.vigentes} vigente{data.vigentes === 1 ? '' : 's'} ahora</span>}
      </div>

      {editando === 'nuevo' && (
        <div className="mb-6">
          <Formulario inicial={VACIO} busy={busy} onGuardar={guardar} onCancelar={() => setEditando(null)} />
        </div>
      )}

      {loading && !data && <div className="text-muted">Cargando…</div>}
      {data && items.length === 0 && editando !== 'nuevo' && (
        <div className="card p-8 shadow-soft text-center text-muted">
          <Megaphone className="mx-auto mb-2" size={22} />
          Todavía no hay avisos. Tommy responde solo con lo que ya sabe.
        </div>
      )}

      <div className="space-y-3">
        {items.map(a => editando === a.id ? (
          <Formulario key={a.id} busy={busy} onGuardar={guardar} onCancelar={() => setEditando(null)}
            inicial={{ titulo: a.titulo, contenido: a.contenido, audiencia: a.audiencia, activo: a.activo,
                       desde: aInput(a.desde), hasta: aInput(a.hasta) }} />
        ) : (
          <div key={a.id} className={`card p-5 shadow-soft ${a.estado === 'vigente' ? '' : 'opacity-75'}`}>
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${ESTADO[a.estado]?.[1]}`}>{ESTADO[a.estado]?.[0] || a.estado}</span>
                  <span className="text-[11px] text-muted">Para: {NOMBRE_AUD[a.audiencia] || a.audiencia}</span>
                </div>
                <div className="text-deep font-semibold mt-1">{a.titulo}</div>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <button onClick={() => alternar(a)} className="text-cobalt-700 flex items-center gap-1">
                  <Power size={14} /> {a.activo ? 'Apagar' : 'Prender'}
                </button>
                <button onClick={() => setEditando(a.id)} className="text-cobalt-700 flex items-center gap-1"><Pencil size={14} /> Editar</button>
                <button onClick={() => borrar(a)} className="text-rose-600 flex items-center gap-1"><Trash2 size={14} /> Borrar</button>
              </div>
            </div>
            <p className="text-sm text-deep mt-2 whitespace-pre-line">{a.contenido}</p>
            <div className="text-[12px] text-muted mt-2">
              {a.desde ? `Desde ${fecha(a.desde)}` : 'Desde que se creó'} · {a.hasta ? `hasta ${fecha(a.hasta)}` : 'sin fecha de fin'}
              {a.actualizado_por ? ` · última edición: ${a.actualizado_por}` : ''}
            </div>
          </div>
        ))}
      </div>

      <div className="card p-5 shadow-soft mt-8">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
          <div className="text-deep font-semibold flex items-center gap-2"><Eye size={16} /> Así lo lee Tommy</div>
          <select id="aviso-preview-tipo" value={tipo} onChange={e => setTipo(e.target.value)}
            className="text-sm border border-border rounded-lg px-3 py-1.5 bg-white/80">
            {[['cliente', 'Si escribe un cliente'], ['asesor', 'Si escribe un asesor'], ['estudiante', 'Si escribe un estudiante'],
              ['prospecto', 'Si escribe un prospecto']].map(([v, n]) => <option key={v} value={v}>{n}</option>)}
          </select>
        </div>
        {preview
          ? <pre className="text-[12px] whitespace-pre-wrap bg-bone-100 rounded-lg p-3 text-deep">{preview}</pre>
          : <div className="text-sm text-muted">No hay avisos vigentes para este tipo de usuario.</div>}
      </div>
    </div>
  )
}
