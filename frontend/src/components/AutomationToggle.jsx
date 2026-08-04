import { useEffect, useState } from 'react'
import { Power } from 'lucide-react'
import api from '../utils/api'
import { useAuth } from '../context/AuthContext'

/**
 * Interruptor global de la automatización de Tomi (kill switch).
 * Solo visible para admins. Prende/apaga desde la plataforma; la lógica de
 * on/off vive en el backend (tabla tomi_settings) — n8n solo obedece el flag.
 */
export default function AutomationToggle() {
  const { isAdmin } = useAuth()
  const [enabled, setEnabled] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = () =>
    api.get('/api/tomi/interruptor/estado').then((r) => setEnabled(r.data.enabled)).catch(() => {})

  useEffect(() => {
    if (!isAdmin) return
    load()
    const t = setInterval(load, 20000)
    return () => clearInterval(t)
  }, [isAdmin])

  if (!isAdmin || enabled === null) return null

  const toggle = async () => {
    const next = !enabled
    const msg = next
      ? '¿Reactivar la automatización? Tomi volverá a responder los mensajes de WhatsApp.'
      : '¿Pausar la automatización? Tomi dejará de responder por WhatsApp hasta que la reactives.'
    if (!window.confirm(msg)) return
    setBusy(true)
    try {
      const r = await api.post('/api/tomi/interruptor/estado', { enabled: next })
      setEnabled(r.data.enabled)
    } catch {
      /* dejamos el estado como estaba; el poll lo re-sincroniza */
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy}
      title={
        enabled
          ? 'Automatización ACTIVA — clic para pausar a Tomi'
          : 'Automatización EN PAUSA — clic para reactivar a Tomi'
      }
      className={`flex items-center gap-2 pl-2.5 pr-3 py-1 rounded-full text-[12px] font-semibold tracking-tight ring-1 transition
        ${
          enabled
            ? 'bg-success/10 text-success ring-success/25 hover:bg-success/15'
            : 'bg-danger/10 text-danger ring-danger/30 hover:bg-danger/15 animate-pulse'
        }
        ${busy ? 'opacity-50 cursor-wait' : ''}`}
    >
      <span className="relative flex h-2 w-2">
        {enabled && (
          <span className="absolute inline-flex h-full w-full rounded-full bg-success/50 animate-ping" />
        )}
        <span
          className={`relative inline-flex h-2 w-2 rounded-full ${
            enabled ? 'bg-success' : 'bg-danger'
          }`}
        />
      </span>
      <Power size={13} strokeWidth={2.4} />
      <span className="hidden sm:inline">{enabled ? 'Tomi activo' : 'Tomi en pausa'}</span>
    </button>
  )
}
