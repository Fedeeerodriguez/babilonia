import { useEffect, useState } from 'react'
import { RefreshCw, CheckCircle2, AlertTriangle, Check, X, Pencil, Clock, ExternalLink } from 'lucide-react'
import tapi, { ticketsAllianzConfigurada } from '../utils/ticketsAllianzApi'

// NOTA: el gestor de tickets Allianz vive FUERA de Tomi (proyecto aparte). Esta sección solo
// consume su API externa (VITE_TICKETS_ALLIANZ_API). No se envía nada al cliente desde acá.

const estadoClass = (e) =>
  e === 'por_cerrar' ? 'bg-rose-100 text-rose-700'
  : e === 'escalado_ceci' ? 'bg-purple-100 text-purple-700'
  : e === 'esperando_cliente' ? 'bg-amber-100 text-amber-700'
  : 'bg-bone-200 text-muted'

const veredictoClass = (v) =>
  v === 'aprobado' ? 'bg-emerald-100 text-emerald-700'
  : v === 'rechazado' ? 'bg-rose-100 text-rose-700'
  : 'bg-amber-100 text-amber-700'

const ETIQUETA = {
  enviar_a_allianz: 'Responder a Allianz', gestionar_tramite: 'Gestionar con Allianz',
  instruir_tramite: 'Instruir al cliente', avisar_cliente: 'Avisar al cliente',
  avisar_asesor: 'Avisar al asesor', escalar_ceci: 'Escalar a Ceci',
  recordatorio_sla: 'Recordatorio SLA', recordatorio: 'Recordatorio',
  consulta_general: 'Consulta a Ceci', reactivacion: 'Reactivar ticket',
}

export default function TicketsAllianz() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(null)        // accion id en proceso
  const [edit, setEdit] = useState({})          // { [accionId]: textoBorrador }

  const load = () => {
    setLoading(true)
    tapi.get('/api/tickets-allianz')
      .then(r => setData(r.data))
      .catch(() => setMsg({ ok: false, text: 'No se pudo cargar el gestor de tickets Allianz.' }))
      .finally(() => setLoading(false))
  }
  useEffect(() => { if (ticketsAllianzConfigurada) load(); else setLoading(false) }, [])

  const patchAccion = (accionId, cambios) =>
    setData(d => ({
      ...d,
      items: d.items.map(t => ({
        ...t,
        acciones: t.acciones.map(a => a.id === accionId ? { ...a, ...cambios } : a),
      })),
    }))

  const veredicto = async (a, v) => {
    setBusy(a.id); setMsg(null)
    try {
      await tapi.post(`/api/tickets-allianz/accion/${a.id}/veredicto`, { veredicto: v, nota: a.nota_revision || null })
      patchAccion(a.id, { veredicto: v })
      setMsg({ ok: true, text: `Acción ${v === 'aprobado' ? 'aprobada' : 'rechazada'} ✓` })
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al guardar el veredicto' })
    } finally { setBusy(null) }
  }

  const guardarBorrador = async (a) => {
    const texto = edit[a.id]
    setBusy(a.id); setMsg(null)
    try {
      await tapi.put(`/api/tickets-allianz/accion/${a.id}/borrador`, { borrador: texto })
      patchAccion(a.id, { borrador: texto, editado: true })
      setEdit(e => { const n = { ...e }; delete n[a.id]; return n })
      setMsg({ ok: true, text: 'Borrador actualizado ✓' })
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al guardar el borrador' })
    } finally { setBusy(null) }
  }

  if (!ticketsAllianzConfigurada) {
    return (
      <div className="max-w-3xl mx-auto animate-fade-in">
        <div className="hero-eyebrow">Sandbox · pre-producción</div>
        <h1 className="hero-title text-4xl text-deep mb-2">Ticket Allianz Seguimiento</h1>
        <div className="card p-6 shadow-soft mt-4">
          <div className="flex items-center gap-2 text-amber-600 mb-2"><AlertTriangle size={18} /> Sección no configurada</div>
          <p className="text-muted text-sm">
            El gestor de tickets Allianz vive en un servicio aparte. Configurá la variable
            <code className="mx-1 px-1.5 py-0.5 rounded bg-bone-200 text-deep text-[12px]">VITE_TICKETS_ALLIANZ_API</code>
            (y opcionalmente <code className="mx-1 px-1.5 py-0.5 rounded bg-bone-200 text-deep text-[12px]">VITE_TICKETS_ALLIANZ_TOKEN</code>)
            con la URL de ese servicio y reconstruí el frontend.
          </p>
        </div>
      </div>
    )
  }

  const r = data?.resumen
  return (
    <div className="max-w-5xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Sandbox · pre-producción</div>
      <h1 className="hero-title text-4xl text-deep mb-2">Ticket Allianz Seguimiento</h1>
      <p className="text-muted font-light mb-6">
        El gestor procesa los correos reales de Allianz y <b>propone</b> las respuestas y acciones — pero
        <b> no envía nada</b> al cliente. Revisá el borrador, editalo si hace falta y aprobá o rechazá.
      </p>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card p-5 shadow-soft">
          <div className="text-[11px] uppercase tracking-wider text-muted">Tickets</div>
          <div className="text-3xl font-semibold text-deep">{r?.tickets ?? '—'}</div>
        </div>
        <div className="card p-5 shadow-soft">
          <div className="text-[11px] uppercase tracking-wider text-muted">Acciones</div>
          <div className="text-3xl font-semibold text-deep">{r?.acciones ?? '—'}</div>
        </div>
        <div className="card p-5 shadow-soft flex items-center justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted">Pendientes</div>
            <div className="text-3xl font-semibold text-amber-600">{r?.pendientes ?? '—'}</div>
          </div>
          <button onClick={load} className="text-cobalt-700 text-sm flex items-center gap-1.5">
            <RefreshCw size={14} /> Recargar
          </button>
        </div>
      </div>

      {msg && (
        <div className={`mb-4 text-[13px] flex items-center gap-1.5 ${msg.ok ? 'text-emerald-600' : 'text-rose-600'}`}>
          {msg.ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />} {msg.text}
        </div>
      )}

      {loading ? (
        <div className="text-muted">Cargando…</div>
      ) : (data?.items || []).length === 0 ? (
        <div className="card p-8 text-center text-muted shadow-soft">No hay tickets para revisar 🎉</div>
      ) : (
        <div className="space-y-4">
          {data.items.map(t => (
            <div key={t.id} className="card shadow-soft overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3 bg-bone-100/60 border-b border-border/60">
                <div className="min-w-0">
                  <div className="font-semibold text-deep truncate">
                    Ticket {t.nro_ticket || 's/n'}
                    {t.cliente_nombre ? <span className="text-muted font-normal"> · {t.cliente_nombre}</span> : null}
                  </div>
                  {t.asunto_hilo && <div className="text-[12px] text-muted truncate">{t.asunto_hilo}</div>}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {t.vence && <span className="text-[11px] text-muted flex items-center gap-1"><Clock size={12} />{String(t.vence).slice(0, 10)}</span>}
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${estadoClass(t.estado)}`}>{t.estado}</span>
                </div>
              </div>

              <div className="divide-y divide-border/50">
                {t.acciones.length === 0 && (
                  <div className="px-5 py-3 text-[12px] text-muted">Sin acciones propuestas.</div>
                )}
                {t.acciones.map(a => (
                  <div key={a.id} className="px-5 py-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-sm font-medium text-deep">
                        {ETIQUETA[a.tipo_accion] || a.tipo_accion}
                        <span className="text-[11px] text-muted font-normal"> · {a.canal}</span>
                        {a.editado && <span className="text-[10px] text-cobalt-700 ml-2">editado</span>}
                      </div>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${veredictoClass(a.veredicto)}`}>
                        {a.veredicto}
                      </span>
                    </div>

                    {edit[a.id] !== undefined ? (
                      <div>
                        <textarea
                          className="w-full text-[13px] border border-border rounded-lg p-2 bg-white/70 min-h-[120px]"
                          value={edit[a.id]}
                          onChange={e => setEdit(s => ({ ...s, [a.id]: e.target.value }))}
                        />
                        <div className="flex gap-2 mt-2">
                          <button disabled={busy === a.id} onClick={() => guardarBorrador(a)}
                            className="btn-primary text-[12px] px-3 py-1.5">Guardar</button>
                          <button onClick={() => setEdit(s => { const n = { ...s }; delete n[a.id]; return n })}
                            className="text-[12px] px-3 py-1.5 text-muted">Cancelar</button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="text-[13px] text-deep/90 whitespace-pre-wrap bg-bone-100/50 rounded-lg p-3 border border-border/50">
                          {a.borrador || <span className="text-muted italic">— sin borrador —</span>}
                        </div>
                        <div className="flex items-center gap-2 mt-2">
                          <button disabled={busy === a.id} onClick={() => veredicto(a, 'aprobado')}
                            className="inline-flex items-center gap-1 text-[12px] px-3 py-1.5 rounded-lg bg-emerald-600 text-white disabled:opacity-50">
                            <Check size={13} /> Aprobar
                          </button>
                          <button disabled={busy === a.id} onClick={() => veredicto(a, 'rechazado')}
                            className="inline-flex items-center gap-1 text-[12px] px-3 py-1.5 rounded-lg bg-rose-600 text-white disabled:opacity-50">
                            <X size={13} /> Rechazar
                          </button>
                          {a.borrador != null && (
                            <button onClick={() => setEdit(s => ({ ...s, [a.id]: a.borrador || '' }))}
                              className="inline-flex items-center gap-1 text-[12px] px-3 py-1.5 rounded-lg border border-border text-muted">
                              <Pencil size={13} /> Editar
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
