import { useEffect, useState } from 'react'
import { Upload, FileText, Plus } from 'lucide-react'
import api from '../utils/api'

const SOURCES = ['plu3', 'patrimonial', 'educacion', 'plu', 'plu4']

export default function Knowledge() {
  const [docs, setDocs] = useState([])
  const [source, setSource] = useState(SOURCES[0])
  const [customSource, setCustomSource] = useState('')
  const [file, setFile] = useState(null)
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = () => api.get('/api/documents').then(r => setDocs(r.data)).catch(()=>{})
  useEffect(() => { load() }, [])

  const finalSource = customSource.trim() || source

  const uploadFile = async (e) => {
    e.preventDefault(); if (!file) return
    setBusy(true); setMsg('')
    const fd = new FormData(); fd.append('source', finalSource); fd.append('file', file)
    try {
      await api.post('/api/documents/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      setMsg('Documento cargado'); setFile(null); load()
    } catch (e) { setMsg(e.response?.data?.detail || 'Error') }
    finally { setBusy(false) }
  }

  const uploadText = async (e) => {
    e.preventDefault(); if (!text || !title) return
    setBusy(true); setMsg('')
    try {
      await api.post('/api/documents/upload-text', { title, source: finalSource, text })
      setMsg('Texto cargado'); setText(''); setTitle(''); load()
    } catch (e) { setMsg(e.response?.data?.detail || 'Error') }
    finally { setBusy(false) }
  }

  return (
    <div className="max-w-6xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Conocimiento</div>
      <h1 className="hero-title text-4xl text-deep mb-2">Base de documentos</h1>
      <p className="text-muted font-light mb-10">Cargá PDFs o texto. El agente Tomi en WATI los va a poder consultar automáticamente.</p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-10">
        <div className="card p-6 shadow-soft">
          <label className="label">Fuente (metadata.source)</label>
          <select className="input" value={source} onChange={(e)=>setSource(e.target.value)}>
            {SOURCES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <label className="label mt-4">o source nuevo</label>
          <div className="flex gap-2">
            <Plus size={14} className="text-muted mt-3.5"/>
            <input className="input" placeholder="ej: alianza_2026" value={customSource} onChange={(e)=>setCustomSource(e.target.value)}/>
          </div>
          <div className="mt-3 text-[11px] text-muted">Se usa: <span className="font-mono text-cobalt-700">{finalSource}</span></div>
        </div>

        <form onSubmit={uploadFile} className="card p-6 shadow-soft">
          <div className="flex items-center gap-2 mb-3"><Upload size={16} className="text-cobalt"/><h3 className="font-semibold text-deep">Subir PDF</h3></div>
          <input type="file" accept=".pdf,.txt,.md" onChange={(e)=>setFile(e.target.files?.[0]||null)} className="block text-[13px] mb-4"/>
          <button disabled={busy || !file} className="btn-primary w-full">{busy ? 'Procesando...' : 'Cargar archivo'}</button>
        </form>

        <form onSubmit={uploadText} className="card p-6 shadow-soft">
          <div className="flex items-center gap-2 mb-3"><FileText size={16} className="text-cobalt"/><h3 className="font-semibold text-deep">Pegar texto</h3></div>
          <input className="input mb-2" placeholder="Título" value={title} onChange={(e)=>setTitle(e.target.value)}/>
          <textarea className="input min-h-[120px]" placeholder="Pegá el texto..." value={text} onChange={(e)=>setText(e.target.value)}/>
          <button disabled={busy || !text || !title} className="btn-primary w-full mt-3">{busy ? 'Procesando...' : 'Cargar texto'}</button>
        </form>
      </div>

      {msg && <div className="mb-6 chip-cobalt">{msg}</div>}

      <h2 className="font-display text-2xl font-semibold text-deep mb-4">Documentos cargados</h2>
      <div className="card overflow-hidden shadow-soft">
        <table className="w-full text-sm">
          <thead className="bg-bone-100/70 text-[11px] uppercase tracking-[0.14em] text-muted">
            <tr>
              <th className="text-left px-5 py-3">Archivo</th>
              <th className="text-left px-5 py-3">Source</th>
              <th className="text-left px-5 py-3">Subido por</th>
              <th className="text-right px-5 py-3">Chunks</th>
              <th className="text-right px-5 py-3">Fecha</th>
            </tr>
          </thead>
          <tbody>
            {docs.map(d => (
              <tr key={d.id} className="border-t border-border/60">
                <td className="px-5 py-3 font-medium text-deep">{d.file_name}</td>
                <td className="px-5 py-3"><span className="chip-cobalt">{d.source}</span></td>
                <td className="px-5 py-3 text-muted">{d.uploaded_by}</td>
                <td className="px-5 py-3 text-right tabular-nums">{d.chunks}</td>
                <td className="px-5 py-3 text-right text-muted text-[12px]">{new Date(d.uploaded_at).toLocaleDateString('es-AR')}</td>
              </tr>
            ))}
            {!docs.length && <tr><td colSpan={5} className="px-5 py-12 text-center text-muted">Sin documentos cargados</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
