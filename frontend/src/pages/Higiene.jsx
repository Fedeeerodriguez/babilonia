import { useEffect, useState } from 'react'
import { Link2, ExternalLink, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react'
import api from '../utils/api'

const scoreClass = (s) =>
  s >= 0.95 ? 'bg-emerald-100 text-emerald-700'
  : s >= 0.88 ? 'bg-amber-100 text-amber-700'
  : 'bg-bone-200 text-muted'

export default function Higiene() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [soloSug, setSoloSug] = useState(true)
  const [busy, setBusy] = useState(null)      // ticket_id en proceso
  const [msg, setMsg] = useState(null)

  const load = () => {
    setLoading(true)
    api.get('/api/higiene/tickets-huerfanos')
      .then(r => setData(r.data))
      .catch(() => setMsg({ ok: false, text: 'No se pudo cargar. ¿Sos admin?' }))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const vincular = async (it) => {
    if (!it.sugerencia) return
    setBusy(it.ticket_id); setMsg(null)
    try {
      await api.post('/api/higiene/vincular', {
        ticket_id: it.ticket_id,
        cliente_id: it.sugerencia.cliente_id,
      })
      // sacar la fila vinculada de la lista
      setData(d => ({
        ...d,
        total: d.total - 1,
        con_sugerencia: d.con_sugerencia - 1,
        items: d.items.filter(x => x.ticket_id !== it.ticket_id),
      }))
      setMsg({ ok: true, text: `Vinculado: ${it.tramite} → ${it.sugerencia.nombre}` })
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al vincular en Notion' })
    } finally { setBusy(null) }
  }

  const items = (data?.items || []).filter(i => !soloSug || i.sugerencia)

  return (
    <div className="max-w-6xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Higiene de datos</div>
      <h1 className="hero-title text-4xl text-deep mb-2">Trámites sin cliente</h1>
      <p className="text-muted font-light mb-6">
        Trámites de Allianz que existen pero no están vinculados a ningún cliente — por eso Tomi
        "no los encuentra". Confirmá la sugerencia y se vinculan en Notion al instante.
      </p>

      {/* Resumen */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
        <div className="card p-5 shadow-soft">
          <div className="text-[11px] uppercase tracking-wider text-muted">Huérfanos</div>
          <div className="text-3xl font-semibold text-deep">{data?.total ?? '—'}</div>
        </div>
        <div className="card p-5 shadow-soft">
          <div className="text-[11px] uppercase tracking-wider text-muted">Con sugerencia</div>
          <div className="text-3xl font-semibold text-emerald-600">{data?.con_sugerencia ?? '—'}</div>
        </div>
        <div className="card p-5 shadow-soft flex items-center justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted">Acciones</div>
            <button onClick={load} className="mt-1 text-cobalt-700 text-sm flex items-center gap-1.5">
              <RefreshCw size={14} /> Recargar
            </button>
          </div>
        </div>
      </div>

      <label className="flex items-center gap-2 mb-4 text-sm text-muted cursor-pointer">
        <input type="checkbox" checked={soloSug} onChange={e => setSoloSug(e.target.checked)} />
        Mostrar solo los que tienen sugerencia
      </label>

      {msg && (
        <div className={`mb-4 text-[13px] flex items-center gap-1.5 ${msg.ok ? 'text-emerald-600' : 'text-rose-600'}`}>
          {msg.ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />} {msg.text}
        </div>
      )}

      {loading ? (
        <div className="text-muted">Cargando…</div>
      ) : (
        <div className="card overflow-hidden shadow-soft">
          <table className="w-full text-sm">
            <thead className="bg-bone-100/70 text-[11px] uppercase tracking-[0.14em] text-muted">
              <tr>
                <th className="text-left px-4 py-3">Trámite</th>
                <th className="text-left px-4 py-3">Tipo / Estado</th>
                <th className="text-left px-4 py-3">Cliente sugerido</th>
                <th className="text-right px-4 py-3">Acción</th>
              </tr>
            </thead>
            <tbody>
              {items.map(it => (
                <tr key={it.ticket_id} className="border-t border-border/60 align-top">
                  <td className="px-4 py-3 font-medium text-deep max-w-[260px]">
                    <div className="truncate">{it.tramite || '—'}</div>
                    {it.url && (
                      <a href={it.url} target="_blank" rel="noreferrer"
                        className="text-[11px] text-cobalt-700 flex items-center gap-1 mt-0.5">
                        <ExternalLink size={11} /> Abrir en Notion
                      </a>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted text-[12px]">
                    {it.tipo || '—'}<br /><span className="text-[11px]">{it.estado || ''}</span>
                  </td>
                  <td className="px-4 py-3">
                    {it.sugerencia ? (
                      <div>
                        <div className="text-deep">{it.sugerencia.nombre}</div>
                        <div className="text-[11px] text-muted">{it.sugerencia.correo || '—'}</div>
                        <span className={`inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${scoreClass(it.sugerencia.score)}`}>
                          {Math.round(it.sugerencia.score * 100)}% match
                        </span>
                      </div>
                    ) : (
                      <span className="text-[12px] text-muted">Sin sugerencia — vincular a mano en Notion</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {it.sugerencia ? (
                      <button disabled={busy === it.ticket_id}
                        onClick={() => vincular(it)}
                        className="btn-primary inline-flex items-center gap-1.5 text-[12px] px-3 py-1.5">
                        <Link2 size={13} /> {busy === it.ticket_id ? 'Vinculando…' : 'Vincular'}
                      </button>
                    ) : (
                      <span className="text-[11px] text-muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-muted">
                  {data?.total === 0 ? '¡No quedan trámites huérfanos! 🎉' : 'Nada para mostrar con el filtro actual.'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
