import { useState } from 'react'
import { Bell, ChevronDown, ChevronRight, UserCheck, AlertTriangle } from 'lucide-react'
import tapi from '../utils/ticketsAllianzApi'

// Etapa 1 del gestor Allianz (proceso largo): en qué etapa está el ticket, cuándo es el próximo
// recordatorio, por qué necesita a Ceci, la línea de tiempo C1→C5 y la asignación manual de
// cliente/asesor cuando el sistema no pudo identificarlos sin adivinar.

export const MOTIVO_CECI = {
  sin_identificar: 'Cliente/asesor sin identificar',
  escalado: 'Escalado',
  para_aprobar: 'Correo para aprobar',
  escalacion_bloqueada: 'Escalación bloqueada',
  revisar: 'Revisar a mano',
  rebote: 'Respuesta rebotada',
}

const PARA = { ceci: 'Ceci', asesor: 'Asesor', cliente: 'Cliente', allianz: 'Allianz' }

const fecha = (v) => {
  if (!v) return '—'
  const d = new Date(String(v).replace(' ', 'T'))
  return isNaN(d) ? String(v).slice(0, 16)
    : d.toLocaleString('es-MX', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'America/Mexico_City' })
}

export function ResumenEtapa({ t }) {
  if (!t.etapa && !(t.para_ceci || []).length) return null
  const p = t.proximo_recordatorio
  return (
    <div className="px-5 pt-3 flex items-center gap-2 flex-wrap text-[12px]">
      {t.etapa && (
        <span className="px-2 py-0.5 rounded-full bg-cobalt-50 text-cobalt-700 font-semibold">
          {t.etapa_nombre || t.etapa}
        </span>
      )}
      {t.producto && <span className="text-muted">{t.producto}{t.nro_solicitud ? ` · sol. ${t.nro_solicitud}` : ''}</span>}
      {p && (
        <span className="text-muted flex items-center gap-1">
          <Bell size={12} /> {p.que === 'escala' ? 'Escala' : 'Recuerda'} {fecha(p.cuando)}
          {p.a_quien?.length ? ` a ${p.a_quien.map(x => PARA[x] || x).join(', ')}` : ''}
        </span>
      )}
      {(t.para_ceci || []).map(m => (
        <span key={m} className="px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 font-semibold flex items-center gap-1">
          <AlertTriangle size={11} /> {MOTIVO_CECI[m] || m}
        </span>
      ))}
    </div>
  )
}

export function LineaTiempo({ ticketId }) {
  const [abierta, setAbierta] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const alternar = () => {
    const abrir = !abierta
    setAbierta(abrir)
    if (abrir && !data) {
      tapi.get(`/api/tickets-allianz/${ticketId}/linea-tiempo`)
        .then(r => setData(r.data))
        .catch(() => setError('No se pudo cargar la línea de tiempo.'))
    }
  }

  return (
    <div className="px-5 pt-3">
      <button onClick={alternar} className="text-[12px] text-cobalt-700 flex items-center gap-1">
        {abierta ? <ChevronDown size={13} /> : <ChevronRight size={13} />} Línea de tiempo
      </button>
      {abierta && (
        <div className="mt-2 rounded-lg border border-border/60 bg-white/60 p-3 text-[12px]">
          {error && <div className="text-rose-600">{error}</div>}
          {!data && !error && <div className="text-muted">Cargando…</div>}
          {data && data.pasos.length === 0 && <div className="text-muted">Todavía no hay etapas registradas.</div>}
          {data && (
            <ol className="space-y-2">
              {data.pasos.map(p => (
                <li key={`${p.etapa}-${p.ronda}`} className="flex gap-3">
                  <span className="text-muted w-24 shrink-0">{fecha(p.fecha)}</span>
                  <div>
                    <div className="text-deep font-medium">{p.etapa_nombre}{p.ronda > 1 ? ` (ronda ${p.ronda})` : ''}</div>
                    <div className="text-muted">
                      Avisos: {p.avisos.map(a => PARA[a.para] || a.para).join(', ') || 'ninguno'}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
          {data && data.recordatorios.length > 0 && (
            <div className="mt-3 pt-2 border-t border-border/50 text-muted">
              {data.recordatorios.map((r, i) => (
                <div key={i}>
                  Recordatorio {r.motivo === 'requerimiento' ? 'del pedido de Allianz' : 'esperando a Allianz'}: {r.estado}
                  {r.estado === 'activo' ? ` · vence ${fecha(r.vence)}` : ''}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function AsignarIdentificacion({ t, onListo }) {
  const [abierto, setAbierto] = useState(false)
  const [f, setF] = useState({ cliente_nombre: t.cliente_nombre || '', telefono_cliente: '', asesor_correo: '', telefono_asesor: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  if (!(t.para_ceci || []).includes('sin_identificar')) return null

  const guardar = async () => {
    setBusy(true); setError(null)
    try {
      await tapi.put(`/api/tickets-allianz/${t.id}/identificacion`, f)
      setAbierto(false)
      onListo?.()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo guardar.')
    } finally { setBusy(false) }
  }

  const campo = (k, label, ph) => (
    <label className="block">
      <span className="text-[11px] text-muted">{label}</span>
      <input id={`ident-${t.id}-${k}`} value={f[k]} placeholder={ph}
        onChange={e => setF(s => ({ ...s, [k]: e.target.value }))}
        className="w-full text-[13px] border border-border rounded-lg px-2 py-1.5 bg-white/80" />
    </label>
  )

  return (
    <div className="px-5 pt-3">
      {!abierto ? (
        <button onClick={() => setAbierto(true)} className="text-[12px] text-cobalt-700 flex items-center gap-1">
          <UserCheck size={13} /> Asignar cliente y asesor
        </button>
      ) : (
        <div className="rounded-lg border border-border/60 bg-white/60 p-3 space-y-2">
          <p className="text-[12px] text-muted">
            El sistema no pudo identificar a esta persona sin adivinar. Lo que cargues acá se usa para los
            próximos avisos y recordatorios de este ticket.
          </p>
          <div className="grid grid-cols-2 gap-2">
            {campo('cliente_nombre', 'Cliente', 'Nombre completo')}
            {campo('telefono_cliente', 'WhatsApp del cliente', '52…')}
            {campo('asesor_correo', 'Correo del asesor', 'asesor@…')}
            {campo('telefono_asesor', 'WhatsApp del asesor', '52…')}
          </div>
          {error && <div className="text-[12px] text-rose-600">{error}</div>}
          <div className="flex gap-2">
            <button disabled={busy} onClick={guardar} className="btn-primary text-[12px] px-3 py-1.5">Guardar</button>
            <button onClick={() => setAbierto(false)} className="text-[12px] px-3 py-1.5 text-muted">Cancelar</button>
          </div>
        </div>
      )}
    </div>
  )
}
