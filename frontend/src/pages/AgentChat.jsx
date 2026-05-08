import { useState, useRef, useEffect } from 'react'
import { Send, Bot } from 'lucide-react'
import api from '../utils/api'

export default function AgentChat() {
  const [history, setHistory] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [history])

  const send = async (e) => {
    e.preventDefault(); if (!input.trim() || busy) return
    const message = input; setInput('')
    setHistory(h => [...h, { role: 'user', content: message }])
    setBusy(true)
    try {
      const { data } = await api.post('/api/agent/chat', { message, history })
      setHistory(h => [...h, { role: 'assistant', content: data.reply }])
    } catch (e) {
      setHistory(h => [...h, { role: 'assistant', content: '(error: ' + (e.response?.data?.detail || e.message) + ')' }])
    } finally { setBusy(false) }
  }

  return (
    <div className="max-w-3xl mx-auto h-[calc(100vh-7rem)] flex flex-col animate-fade-in">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-full bg-cobalt grid place-items-center"><Bot size={18} className="text-white"/></div>
        <div>
          <div className="hero-eyebrow !mb-0">Asistente interno</div>
          <h1 className="font-display text-2xl font-bold text-deep">Tomi</h1>
        </div>
      </div>

      <div className="flex-1 card p-6 shadow-soft overflow-y-auto space-y-4">
        {!history.length && (
          <div className="text-muted text-sm">
            Hola. Preguntame sobre métricas, conversaciones o pedime que cargue información a la base de conocimiento.
          </div>
        )}
        {history.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-[14px] whitespace-pre-wrap leading-relaxed ${
              m.role === 'user' ? 'bg-deep text-bone' : 'bg-bone-100 text-deep'
            }`}>{m.content}</div>
          </div>
        ))}
        {busy && <div className="text-muted text-sm animate-pulse">Tomi está pensando...</div>}
        <div ref={endRef}/>
      </div>

      <form onSubmit={send} className="mt-4 flex gap-2">
        <input className="input flex-1" placeholder="Escribí tu mensaje..." value={input} onChange={(e)=>setInput(e.target.value)} disabled={busy}/>
        <button className="btn-primary" disabled={busy || !input.trim()}><Send size={15}/></button>
      </form>
    </div>
  )
}
