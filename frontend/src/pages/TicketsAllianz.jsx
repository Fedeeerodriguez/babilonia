import { useEffect, useState } from 'react'
import {
  RefreshCw, CheckCircle2, AlertTriangle, Pencil, Clock, Mail,
  ThumbsUp, ThumbsDown, Meh, Target, Send,
} from 'lucide-react'
import tapi, { ticketsAllianzConfigurada } from '../utils/ticketsAllianzApi'

// NOTA: el gestor de tickets Allianz vive FUERA de Tomi (proyecto aparte). Esta sección solo
// consume su API externa (VITE_TICKETS_ALLIANZ_API). No se envía nada al cliente desde acá.
// Los botones Buena / Regular / Mala son feedback del equipo para evaluar al agente.

const estadoClass = (e) =>
  e === 'por_cerrar' ? 'bg-rose-100 text-rose-700'
  : e === 'escalado_ceci' ? 'bg-purple-100 text-purple-700'
  : e === 'esperando_cliente' ? 'bg-amber-100 text-amber-700'
  : 'bg-bone-200 text-muted'

const ETIQUETA = {
  enviar_a_allianz: 'Responder a Allianz', gestionar_tramite: 'Gestionar con Allianz',
  instruir_tramite: 'Instruir al cliente', avisar_cliente: 'Avisar al cliente',
  avisar_asesor: 'Avisar al asesor', escalar_ceci: 'Escalar a Ceci',
  recordatorio_sla: 'Recordatorio SLA', recordatorio: 'Recordatorio',
  consulta_general: 'Consulta a Ceci', reactivacion: 'Reactivar ticket',
}

// Buena / Regular / Mala — definición de cada botón
const CALIFS = [
  { key: 'buena',   label: 'Buena',   Icon: ThumbsUp,   on: 'bg-emerald-600 text-white border-emerald-600', off: 'text-emerald-700 border-emerald-200 hover:bg-emerald-50' },
  { key: 'regular', label: 'Regular', Icon: Meh,        on: 'bg-amber-500 text-white border-amber-500',      off: 'text-amber-700 border-amber-200 hover:bg-amber-50' },
  { key: 'mala',    label: 'Mala',    Icon: ThumbsDown, on: 'bg-rose-600 text-white border-rose-600',        off: 'text-rose-700 border-rose-200 hover:bg-rose-50' },
]

const chipCalif = (c) =>
  c === 'buena' ? 'bg-emerald-100 text-emerald-700'
  : c === 'regular' ? 'bg-amber-100 text-amber-700'
  : c === 'mala' ? 'bg-rose-100 text-rose-700'
  : 'bg-bone-200 text-muted'

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

  const calificar = async (a, c) => {
    setBusy(a.id); setMsg(null)
    try {
      await tapi.post(`/api/tickets-allianz/accion/${a.id}/calificacion`, { calificacion: c, nota: a.nota_revision || null })
      patchAccion(a.id, { calificacion: c })
      setMsg({ ok: true, text: `Respuesta marcada como ${c} ✓` })
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al guardar la calificación' })
    } finally { setBusy(null) }
  }

  const guardarBorrador = async (a) => {
    const texto = edit[a.id]
    setBusy(a.id); setMsg(null)
    try {
      await tapi.put(`/api/tickets-allianz/accion/${a.id}/borrador`, { borrador: texto })
      patchAccion(a.id, { borrador: texto, editado: true })
      setEdit(e => { const n = { ...e }; delete n[a.id]; return n })
      setMsg({ ok: true, text: 'Mensaje actualizado ✓' })
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al guardar el mensaje' })
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
        Por cada correo, el agente <b>propone</b> una acción y redacta el mensaje — pero <b>no envía nada</b> al
        cliente. Leé lo que decía el correo, revisá la respuesta, editala si hace falta y calificala
        <b> Buena</b>, <b>Regular</b> o <b>Mala</b> para que el agente mejore.
      </p>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card p-5 shadow-soft">
          <div className="text-[11px] uppercase tracking-wider text-muted">Tickets</div>
          <div className="text-3xl font-semibold text-deep">{r?.tickets ?? '—'}</div>
        </div>
        <div className="card p-5 shadow-soft">
          <div className="text-[11px] uppercase tracking-wider text-muted">Respuestas</div>
          <div className="text-3xl font-semibold text-deep">{r?.acciones ?? '—'}</div>
        </div>
        <div className="card p-5 shadow-soft flex items-center justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted">Sin calificar</div>
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
        <div className="space-y-5">
          {data.items.map(t => (
            <div key={t.id} className="card shadow-soft overflow-hidden">
              {/* Cabecera del ticket */}
              <div className="flex items-center justify-between px-5 py-3 bg-bone-100/60 border-b border-border/60">
                <div className="min-w-0">
                  <div className="font-semibold text-deep truncate">
                    Ticket {t.nro_ticket || 's/n'}
                    {t.cliente_nombre ? <span className="text-muted font-normal"> · {t.cliente_nombre}</span> : null}
                    {t.delicado && <span className="ml-2 px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 text-[10px] font-semibold">delicado</span>}
                  </div>
                  {t.asunto_hilo && <div className="text-[12px] text-muted truncate">{t.asunto_hilo}</div>}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {t.vence && <span className="text-[11px] text-muted flex items-center gap-1"><Clock size={12} />{String(t.vence).slice(0, 10)}</span>}
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${estadoClass(t.estado)}`}>{t.estado}</span>
                </div>
              </div>

              {/* 1. Qué decía el correo */}
              {t.correo && (
                <div className="px-5 pt-4">
                  <div className="text-[11px] uppercase tracking-wider text-muted flex items-center gap-1.5 mb-1.5">
                    <Mail size={13} /> Lo que decía el correo
                  </div>
                  <div className="rounded-lg border border-border/60 bg-white/60 overflow-hidden">
                    <div className="px-3 py-2 border-b border-border/50 text-[12px] text-muted">
                      {t.correo.remitente && <span className="text-deep font-medium">{t.correo.remitente}</span>}
                      {t.correo.asunto && <span className="block truncate">Asunto: {t.correo.asunto}</span>}
                    </div>
                    <div className="px-3 py-2 text-[13px] text-deep/85 whitespace-pre-wrap max-h-48 overflow-y-auto">
                      {t.correo.cuerpo?.trim() || <span className="text-muted italic">— sin cuerpo —</span>}
                    </div>
                  </div>
                </div>
              )}

              {/* Acciones propuestas */}
              <div className="px-5 py-4 space-y-4">
                {t.acciones.length === 0 && (
                  <div className="text-[12px] text-muted">Sin acciones propuestas.</div>
                )}
                {t.acciones.map(a => (
                  <div key={a.id} className="rounded-lg border border-border/50 bg-bone-100/30 p-3.5">
                    {/* 2. Qué acción piensa hacer */}
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-[11px] uppercase tracking-wider text-muted flex items-center gap-1.5">
                        <Target size={13} /> Acción del agente
                      </div>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${chipCalif(a.calificacion)}`}>
                        {a.calificacion === 'pendiente' ? 'sin calificar' : a.calificacion}
                      </span>
                    </div>
                    <div className="text-sm font-medium text-deep mb-3">
                      {ETIQUETA[a.tipo_accion] || a.tipo_accion}
                      <span className="text-[11px] text-muted font-normal"> · vía {a.canal}</span>
                      {a.editado && <span className="text-[10px] text-cobalt-700 ml-2">✎ editado a mano</span>}
                    </div>

                    {/* 3. Qué mensaje enviaría  /  5. Editar */}
                    <div className="text-[11px] uppercase tracking-wider text-muted flex items-center gap-1.5 mb-1.5">
                      <Send size={12} /> Mensaje que enviaría
                    </div>
                    {edit[a.id] !== undefined ? (
                      <div>
                        <textarea
                          className="w-full text-[13px] border border-border rounded-lg p-2 bg-white/80 min-h-[140px]"
                          value={edit[a.id]}
                          onChange={e => setEdit(s => ({ ...s, [a.id]: e.target.value }))}
                        />
                        <div className="flex gap-2 mt-2">
                          <button disabled={busy === a.id} onClick={() => guardarBorrador(a)}
                            className="btn-primary text-[12px] px-3 py-1.5">Guardar mensaje</button>
                          <button onClick={() => setEdit(s => { const n = { ...s }; delete n[a.id]; return n })}
                            className="text-[12px] px-3 py-1.5 text-muted">Cancelar</button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="text-[13px] text-deep/90 whitespace-pre-wrap bg-white/70 rounded-lg p-3 border border-border/50">
                          {a.borrador || <span className="text-muted italic">— sin mensaje —</span>}
                        </div>

                        {/* 4. Botones Buena / Regular / Mala + Editar */}
                        <div className="flex items-center gap-2 mt-3 flex-wrap">
                          <span className="text-[11px] text-muted mr-1">¿Cómo está la respuesta?</span>
                          {CALIFS.map(({ key, label, Icon, on, off }) => {
                            const sel = a.calificacion === key
                            return (
                              <button key={key} disabled={busy === a.id} onClick={() => calificar(a, key)}
                                className={`inline-flex items-center gap-1 text-[12px] px-3 py-1.5 rounded-lg border transition disabled:opacity-50 ${sel ? on : off}`}>
                                <Icon size={13} /> {label}
                              </button>
                            )
                          })}
                          {a.borrador != null && (
                            <button onClick={() => setEdit(s => ({ ...s, [a.id]: a.borrador || '' }))}
                              className="inline-flex items-center gap-1 text-[12px] px-3 py-1.5 rounded-lg border border-border text-muted ml-auto">
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
