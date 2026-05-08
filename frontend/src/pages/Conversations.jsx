import { useEffect, useState } from 'react'
import { Search, X } from 'lucide-react'
import api from '../utils/api'

export default function Conversations() {
  const [list, setList] = useState([])
  const [q, setQ] = useState('')
  const [active, setActive] = useState(null)
  const [thread, setThread] = useState([])

  useEffect(() => {
    const t = setTimeout(() => {
      api.get('/api/conversations', { params: q ? { q } : {} })
         .then(r => setList(r.data)).catch(()=>{})
    }, 250)
    return () => clearTimeout(t)
  }, [q])

  const open = (c) => {
    setActive(c)
    api.get(`/api/conversations/${c.wa_id}`).then(r => setThread(r.data)).catch(()=>{})
  }

  return (
    <div className="max-w-7xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Soporte</div>
      <h1 className="hero-title text-4xl text-deep mb-8">Conversaciones</h1>

      <div className="relative mb-5 max-w-md">
        <Search size={15} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted"/>
        <input className="input pl-10" placeholder="Buscar por número o nombre..." value={q} onChange={(e)=>setQ(e.target.value)} />
      </div>

      <div className="card overflow-hidden shadow-soft">
        <table className="w-full text-sm">
          <thead className="bg-bone-100/70 text-[11px] uppercase tracking-[0.14em] text-muted">
            <tr>
              <th className="text-left px-5 py-3">Cliente</th>
              <th className="text-left px-5 py-3">WaId</th>
              <th className="text-left px-5 py-3">Último mensaje</th>
              <th className="text-right px-5 py-3">Mensajes</th>
              <th className="text-right px-5 py-3">Última actividad</th>
            </tr>
          </thead>
          <tbody>
            {list.map((c) => (
              <tr key={c.wa_id} onClick={()=>open(c)}
                className="border-t border-border/60 hover:bg-bone-100/50 cursor-pointer transition">
                <td className="px-5 py-3 font-medium text-deep">{c.sender_name || '—'}</td>
                <td className="px-5 py-3 text-muted font-mono text-[12px]">{c.wa_id}</td>
                <td className="px-5 py-3 text-muted truncate max-w-[28ch]">{c.last_content}</td>
                <td className="px-5 py-3 text-right">{c.message_count}</td>
                <td className="px-5 py-3 text-right text-muted text-[12px]">
                  {new Date(c.last_message_at).toLocaleString('es-AR')}
                </td>
              </tr>
            ))}
            {!list.length && <tr><td colSpan={5} className="px-5 py-12 text-center text-muted">Sin resultados</td></tr>}
          </tbody>
        </table>
      </div>

      {active && (
        <div className="fixed inset-0 z-50 bg-deep/30 backdrop-blur-sm flex justify-end" onClick={()=>setActive(null)}>
          <div className="w-full max-w-xl bg-white h-full overflow-y-auto p-8 animate-slide-up" onClick={(e)=>e.stopPropagation()}>
            <div className="flex items-start justify-between mb-6">
              <div>
                <div className="hero-eyebrow">Conversación</div>
                <h2 className="font-display text-2xl font-semibold text-deep">{active.sender_name || active.wa_id}</h2>
                <div className="text-muted text-[12px] font-mono">{active.wa_id}</div>
              </div>
              <button onClick={()=>setActive(null)} className="p-2 rounded-full hover:bg-bone-200/70"><X size={16}/></button>
            </div>
            <div className="space-y-3">
              {thread.map(m => <Bubble key={m.id} m={m} />)}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Bubble({ m }) {
  const isClient = m.direction === 'cliente'
  const tone = {
    cliente:  'bg-bone-100 text-deep',
    asesor:   'bg-deep text-bone',
    bot:      'bg-cobalt-50 text-cobalt-800 border border-cobalt-200',
    template: 'bg-cobalt text-white',
  }[m.direction] || 'bg-bone-100'
  return (
    <div className={`flex ${isClient ? 'justify-start' : 'justify-end'}`}>
      <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-[13px] ${tone}`}>
        <div className="opacity-60 text-[10px] uppercase tracking-[0.12em] mb-1">
          {m.direction}{m.operator_name ? ` · ${m.operator_name}` : ''} · {new Date(m.created_at).toLocaleString('es-AR')}
        </div>
        <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
      </div>
    </div>
  )
}
