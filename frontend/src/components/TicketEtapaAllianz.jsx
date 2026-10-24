import { useState } from 'react'
import { Bell, ChevronDown, ChevronRight, UserCheck, AlertTriangle, FileCheck2, Send, FilePlus2, Paperclip, Eye } from 'lucide-react'
import tapi from '../utils/ticketsAllianzApi'

// Etapa 1 del gestor Allianz (proceso largo): en qué etapa está el ticket, cuándo es el próximo
// recordatorio, por qué necesita a Ceci, la línea de tiempo C1→C5 y la asignación manual de
// cliente/asesor cuando el sistema no pudo identificarlos sin adivinar.
// Etapa 2 (proceso corto + trámites): la guía de aportación que Ceci aprueba antes de que salga y
// el botón para marcar a mano el pago (Patrimonial) o una respuesta mandada por fuera.
// Etapa 3: abrir un trámite desde el panel y aprobar los correos retenidos para Ceci.

export const MOTIVO_CECI = {
  sin_identificar: 'Cliente/asesor sin identificar',
  escalado: 'Escalado',
  para_aprobar: 'Correo para aprobar',
  escalacion_bloqueada: 'Escalación bloqueada',
  revisar: 'Revisar a mano',
  rebote: 'Respuesta rebotada',
  guia_por_aprobar: 'Guía de aportación por aprobar',
}

const PROCESO = { largo: 'Proceso largo', corto: 'Proceso corto', tramite: 'Trámite' }
const RECORDATORIO = { requerimiento: 'del pedido de Allianz', esperando_allianz: 'esperando a Allianz', pago: 'del pago' }

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
      {t.proceso && t.proceso !== 'largo' && <span className="text-muted">{PROCESO[t.proceso] || t.proceso}</span>}
      {t.titulo_hilo && <span className="text-deep font-medium">«{t.titulo_hilo}»</span>}
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
                  Recordatorio {RECORDATORIO[r.motivo] || r.motivo}: {r.estado}
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


// ─────────────── Etapa 2 ───────────────
// Lo que Ceci completa o confirma en la guía depende del producto (lo manda la API en `campos`):
// Patrimonial y Elite → monto y n° de solicitud (este ya viene del correo de Allianz); OptiMaxx Plus → monto y datos.
const CAMPO_GUIA = {
  monto: ['Monto', '$50,000 MXN'],
  datos_deposito: ['Datos para depositar', 'CLABE 0123… a nombre de Allianz México'],
  solicitud: ['Número de solicitud', '25290001'],
}

export function GuiaAportacion({ t, onListo }) {
  const g = t.guia_pendiente
  const campos = g?.campos || [
    { clave: 'monto', valor: g?.monto || '' }, { clave: 'datos_deposito', valor: g?.datos_deposito || '' },
  ]
  const [f, setF] = useState(Object.fromEntries(campos.map(c => [c.clave, c.valor || ''])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  if (!g) return null
  const val = (k) => (f[k] || '').trim()
  const completa = campos.every(c => val(c.clave))
  const cambiado = campos.some(c => val(c.clave) !== (c.valor || ''))
  const confirma = campos.some(c => c.clave === 'solicitud')
  const sinDatos = g.faltan_del_ticket || []  // póliza / n° de ticket / nombre: sin eso no se aprueba
  // La guía sale por la plantilla de WhatsApp: solo cambian estos datos; el resto lo pone el sistema.
  let vista = g.texto || ''
  for (const c of campos) {
    const nuevo = val(c.clave) || '[completar]'
    // Guía general (OptiMaxx Plus): líneas "• Monto:" / "• Datos para depositar:". Las de Patrimonial y
    // Elite llevan el monto y el n° de solicitud dentro del texto: se reemplaza el valor anterior.
    if (c.clave === 'monto' && /• Monto: /.test(vista)) vista = vista.replace(/• Monto: .*/, `• Monto: ${nuevo}`)
    else if (c.clave === 'datos_deposito') vista = vista.replace(/• Datos para depositar: .*/, `• Datos para depositar: ${nuevo}`)
    else if (c.valor) vista = vista.split(c.valor).join(nuevo)
    else vista = vista.replace('[completar]', nuevo)
  }

  const mandar = async (accion, extra = {}) => {
    if (accion === 'descartar' && !window.confirm('¿Descartar la guía? No se le manda nada al cliente.')) return
    setBusy(true); setError(null)
    try {
      const r = await tapi.post(`/api/tickets-allianz/aprobacion/${g.id}`, { accion, usuario: 'Ceci', ...extra })
      onListo?.(r.data?.motivo)
    } catch (err) {
      const detalle = err.response?.data?.detail || 'No se pudo guardar.'
      // Al aprobar, el sistema completó la guía con datos nuevos del ticket: recargar para ver la versión nueva.
      if (/revisa la versión \d+/.test(detalle)) onListo?.(detalle)
      else setError(detalle)
    } finally { setBusy(false) }
  }
  const valores = () => Object.fromEntries(campos.map(c => [c.clave, val(c.clave)]))

  return (
    <div className="px-5 pt-3">
      <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 space-y-2">
        <div className="text-[12px] font-semibold text-deep flex items-center gap-1">
          <FileCheck2 size={13} /> Guía de aportación — versión {g.version}
          {g.por_telegram && <span className="font-normal text-muted"> · también está en tu Telegram</span>}
        </div>
        <p className="text-[12px] text-muted">
          No sale al cliente ni al asesor hasta que la apruebes.{' '}
          {confirma ? 'Completa el monto y revisa que el número de solicitud sea el correcto: es la referencia del pago.'
                    : 'Completa el monto y los datos para depositar.'}
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {campos.map(({ clave }) => (
            <label key={clave} className="block">
              <span className="text-[11px] text-muted">{(CAMPO_GUIA[clave] || [clave])[0]}</span>
              <input id={`guia-${g.id}-${clave}`} value={f[clave] || ''} placeholder={(CAMPO_GUIA[clave] || [])[1]}
                onChange={e => setF(s => ({ ...s, [clave]: e.target.value }))}
                className="w-full text-[13px] border border-border rounded-lg px-2 py-1.5 bg-white/90" />
            </label>
          ))}
        </div>
        <div className="text-[11px] text-muted">Así le llega al cliente:</div>
        <pre className="text-[12px] whitespace-pre-wrap bg-white/80 rounded-lg p-2 text-deep font-sans">{vista}</pre>
        {sinDatos.length > 0 && (
          <div className="text-[12px] text-rose-600">
            Al ticket le falta {sinDatos.join(' y ')}: así la guía le llega rota al cliente. Descártala y mándala a mano.
          </div>
        )}
        {error && <div className="text-[12px] text-rose-600">{error}</div>}
        <div className="flex gap-2 flex-wrap">
          <button disabled={busy || !completa || sinDatos.length > 0} onClick={() => mandar('aprobar', valores())}
            className="btn-primary text-[12px] px-3 py-1.5">Aprobar y enviar</button>
          <button disabled={busy || !cambiado} onClick={() => mandar('corregir', valores())}
            className="text-[12px] px-3 py-1.5 border border-border rounded-lg bg-white/80">Guardar sin enviar</button>
          <button disabled={busy} onClick={() => mandar('descartar')}
            className="text-[12px] px-3 py-1.5 text-rose-600">Descartar</button>
        </div>
      </div>
    </div>
  )
}

export function MarcarEnviado({ t, onListo }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const corto = t.proceso === 'corto'
  // Corto: después de la guía, el pago (Patrimonial va por un correo nuevo y no vuelve al hilo).
  // Cualquier proceso: una respuesta a un pedido de Allianz que se mandó por fuera del hilo.
  const visible = !t.guia_pendiente && (t.estado || '') !== 'resuelto' &&
    ((corto && ['confirmacion_datos', 'requerimiento'].includes(t.etapa)) || t.etapa === 'requerimiento')
  if (!visible) return null
  const etiqueta = corto ? 'Marcar pago enviado' : 'Marcar respuesta enviada'

  const marcar = async () => {
    const q = corto
      ? '¿Ya se le mandó a Allianz el comprobante de pago? Se avisa al cliente y al asesor.'
      : '¿Ya se le mandó a Allianz lo que pidió? Se avisa al cliente y al asesor.'
    if (!window.confirm(q)) return
    setBusy(true); setError(null)
    try {
      await tapi.post(`/api/tickets-allianz/${t.id}/etapa`, { etapa: 'documentos_enviados', usuario: 'Ceci' })
      onListo?.()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo marcar.')
    } finally { setBusy(false) }
  }

  return (
    <div className="px-5 pt-3 flex items-center gap-2">
      <button disabled={busy} onClick={marcar} className="text-[12px] text-cobalt-700 flex items-center gap-1">
        <Send size={13} /> {etiqueta}
      </button>
      {error && <span className="text-[12px] text-rose-600">{error}</span>}
    </div>
  )
}

// Etapa 3: correos retenidos para el visto bueno de Ceci (escalación a Allianz con copia a la
// ejecutiva, temas críticos). Sale el borrador tal como está (con lo que se haya editado).
export function AprobarCorreo({ a, onListo }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  if (a.estado !== 'pendiente_ceci') return null

  const decidir = async (decision) => {
    const a_quien = a.canal === 'email_cliente' ? 'al cliente' : 'a Allianz'  // los críticos van al cliente
    const q = decision === 'enviar'
      ? `¿Enviar este correo ${a_quien} tal como está? Sale en el próximo ciclo.`
      : '¿Descartar este correo? No se manda.'
    if (!window.confirm(q)) return
    setBusy(true); setError(null)
    try {
      const r = await tapi.post(`/api/tickets-allianz/accion/${a.id}/aprobar`, { decision, usuario: 'Ceci' })
      onListo?.(r.data?.motivo)
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo guardar.')
    } finally { setBusy(false) }
  }

  return (
    <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/60 p-2.5 flex items-center gap-2 flex-wrap">
      <span className="text-[12px] text-deep flex items-center gap-1">
        <AlertTriangle size={13} className="text-amber-600" /> Espera tu aprobación: no sale hasta que lo envíes.
      </span>
      <button disabled={busy} onClick={() => decidir('enviar')} className="btn-primary text-[12px] px-3 py-1.5 ml-auto">Enviar</button>
      <button disabled={busy} onClick={() => decidir('descartar')} className="text-[12px] px-3 py-1.5 text-rose-600">Descartar</button>
      {error && <span className="text-[12px] text-rose-600 w-full">{error}</span>}
    </div>
  )
}

// Etapa 3: abrir un trámite ante Allianz desde el panel. El sistema identifica la póliza en
// Notion, arma el correo (asunto fijo para reconocer la respuesta) y lo manda desde hola@.
const leerArchivo = (file) => new Promise((ok, mal) => {
  const r = new FileReader()
  r.onload = () => ok({ nombre: file.name, tipo: file.type, base64: String(r.result).split(',')[1] || '' })
  r.onerror = () => mal(new Error(`No se pudo leer ${file.name}`))
  r.readAsDataURL(file)
})

const VACIO = { tramite: '', otro: '', poliza: '', nota: '' }

export function AbrirTramite({ onListo }) {
  const [abierto, setAbierto] = useState(false)
  const [catalogo, setCatalogo] = useState([])
  const [f, setF] = useState(VACIO)
  const [archivos, setArchivos] = useState([])
  const [vista, setVista] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const abrirForm = async () => {
    setAbierto(a => !a)
    if (!catalogo.length) {
      try { setCatalogo((await tapi.get('/api/tickets-allianz/tramites/catalogo')).data.tramites || []) }
      catch { setError('No se pudo cargar la lista de trámites.') }
    }
  }
  const cambiar = (k, v) => { setF(s => ({ ...s, [k]: v })); setVista(null) }
  const cuerpo = async () => ({
    tramite: f.tramite === 'otro' ? f.otro.trim() : f.tramite,
    poliza: f.poliza.trim(), nota: f.nota.trim() || null, usuario: 'Ceci',
    adjuntos: await Promise.all(archivos.map(leerArchivo)),
  })

  const verVista = async () => {
    setBusy(true); setError(null); setVista(null)
    try {
      const r = (await tapi.post('/api/tickets-allianz/tramites/vista-previa', await cuerpo())).data
      if (r.ok) setVista(r); else setError(r.motivo)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'No se pudo armar la vista previa.')
    } finally { setBusy(false) }
  }

  const abrir = async () => {
    setBusy(true); setError(null)
    try {
      const r = (await tapi.post('/api/tickets-allianz/tramites', await cuerpo())).data
      setF(VACIO); setArchivos([]); setVista(null); setAbierto(false)
      onListo?.(r.sin_destino ? 'Trámite abierto, pero falta el correo de Allianz (ALLIANZ_DEST): queda bloqueado'
                              : 'Trámite abierto: el correo sale en el próximo ciclo')
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo abrir el trámite.')
    } finally { setBusy(false) }
  }

  const listo = f.tramite && (f.tramite !== 'otro' || f.otro.trim()) && f.poliza.trim()
  const entrada = 'w-full text-[13px] border border-border rounded-lg px-2 py-1.5 bg-white/90'
  return (
    <div className="card shadow-soft mb-5">
      <button onClick={abrirForm} className="w-full px-5 py-3 flex items-center gap-2 text-sm font-semibold text-deep">
        {abierto ? <ChevronDown size={15} /> : <ChevronRight size={15} />} <FilePlus2 size={15} /> Abrir un trámite con Allianz
      </button>
      {abierto && (
        <div className="px-5 pb-4 space-y-3">
          <p className="text-[12px] text-muted">
            El correo sale desde hola@, así la respuesta de Allianz llega al sistema y se le da seguimiento solo.
            Al cliente y al asesor se les avisa cuando Allianz confirma el ticket.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <label className="block">
              <span className="text-[11px] text-muted">Trámite</span>
              <select id="tramite-tipo" value={f.tramite} onChange={e => cambiar('tramite', e.target.value)} className={entrada}>
                <option value="">Elige…</option>
                {catalogo.map(t => (
                  <option key={t.clave} value={t.clave}>{t.nombre}{t.nosotros ? '' : ' (el cliente lo puede hacer en su portal)'}</option>
                ))}
                <option value="otro">Otro…</option>
              </select>
            </label>
            <label className="block">
              <span className="text-[11px] text-muted">Póliza</span>
              <input id="tramite-poliza" value={f.poliza} placeholder="PLU3-408444"
                onChange={e => cambiar('poliza', e.target.value)} className={entrada} />
            </label>
          </div>
          {f.tramite === 'otro' && (
            <input id="tramite-otro" value={f.otro} placeholder="Nombre del trámite (ej. Aplicación de pago)"
              onChange={e => cambiar('otro', e.target.value)} className={entrada} />
          )}
          <textarea id="tramite-nota" value={f.nota} placeholder="Detalle para Allianz (opcional)"
            onChange={e => cambiar('nota', e.target.value)} className={`${entrada} min-h-[70px]`} />
          <label className="text-[12px] text-cobalt-700 flex items-center gap-1 cursor-pointer w-fit">
            <Paperclip size={13} /> Adjuntar archivos
            <input id="tramite-adjuntos" type="file" multiple className="hidden"
              onChange={e => { setArchivos(Array.from(e.target.files || [])); setVista(null) }} />
          </label>
          {archivos.length > 0 && <div className="text-[12px] text-muted">{archivos.map(a => a.name).join(' · ')}</div>}

          {vista && (
            <div className="rounded-lg border border-border/60 bg-white/70 p-3 space-y-1.5 text-[12px]">
              <div><b>Cliente:</b> {vista.cliente || '—'} · <b>Asesor:</b> {vista.asesor || '—'}</div>
              <div><b>Para:</b> {vista.destino || <span className="text-rose-600">falta el correo de Allianz (ALLIANZ_DEST)</span>}</div>
              <div><b>Asunto:</b> {vista.asunto}</div>
              <pre className="whitespace-pre-wrap font-sans text-deep bg-bone-100/50 rounded p-2">{vista.cuerpo}</pre>
            </div>
          )}
          {error && <div className="text-[12px] text-rose-600">{error}</div>}
          <div className="flex gap-2">
            <button disabled={busy || !listo} onClick={verVista}
              className="text-[12px] px-3 py-1.5 border border-border rounded-lg bg-white/80 flex items-center gap-1">
              <Eye size={13} /> Ver cómo sale
            </button>
            <button disabled={busy || !vista} onClick={abrir} className="btn-primary text-[12px] px-3 py-1.5">Abrir trámite</button>
          </div>
        </div>
      )}
    </div>
  )
}
