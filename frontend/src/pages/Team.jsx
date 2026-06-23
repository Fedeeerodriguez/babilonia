import { useEffect, useState } from 'react'
import { UserPlus, Shield, ShieldCheck, User as UserIcon } from 'lucide-react'
import api from '../utils/api'
import { useAuth } from '../context/AuthContext'

const ROLES = [
  { key: 'asesor', label: 'Asesor', icon: UserIcon },
  { key: 'admin', label: 'Admin', icon: Shield },
  { key: 'super_admin', label: 'Super Admin', icon: ShieldCheck },
]
const roleLabel = (r) => ({ asesor: 'Asesor', admin: 'Admin', super_admin: 'Super Admin' }[r] || r)
const roleClass = (r) => ({
  super_admin: 'bg-purple-100 text-purple-700',
  admin: 'bg-cobalt-100 text-cobalt-700',
  asesor: 'bg-bone-200 text-muted',
}[r] || 'bg-bone-200 text-muted')

export default function Team() {
  const { isSuperAdmin } = useAuth()
  const [users, setUsers] = useState([])
  const [form, setForm] = useState({ email: '', full_name: '', operator_name: '', password: '', role: 'asesor' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const load = () => api.get('/api/users').then(r => setUsers(r.data)).catch(() => {})
  useEffect(() => { load() }, [])

  const crear = async (e) => {
    e.preventDefault()
    setBusy(true); setMsg(null)
    try {
      await api.post('/api/users', form)
      setForm({ email: '', full_name: '', operator_name: '', password: '', role: 'asesor' })
      setMsg({ ok: true, text: 'Usuario creado.' })
      load()
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al crear el usuario' })
    } finally { setBusy(false) }
  }

  const cambiarRol = async (u, role) => {
    if (role === u.role) return
    try { await api.patch(`/api/users/${u.id}`, { role }); load() }
    catch (err) { setMsg({ ok: false, text: err.response?.data?.detail || 'Error al cambiar el rol' }) }
  }

  const toggleActivo = async (u) => {
    try { await api.patch(`/api/users/${u.id}`, { is_active: !u.is_active }); load() }
    catch (err) { setMsg({ ok: false, text: err.response?.data?.detail || 'Error' }) }
  }

  return (
    <div className="max-w-5xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Administración</div>
      <h1 className="hero-title text-4xl text-deep mb-2">Usuarios</h1>
      <p className="text-muted font-light mb-8">
        Admins y super-admins ven toda la plataforma y pueden evaluar el sandbox. Solo un super-admin crea admins/super-admins.
      </p>

      {/* Alta de usuario */}
      <form onSubmit={crear} className="card p-6 shadow-soft mb-8">
        <div className="flex items-center gap-2 mb-4 text-deep font-semibold"><UserPlus size={18} /> Crear usuario</div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <div className="label">Email</div>
            <input className="input" type="email" required value={form.email}
              onChange={e => setForm({ ...form, email: e.target.value })} placeholder="persona@babilonia.com" />
          </div>
          <div>
            <div className="label">Nombre</div>
            <input className="input" value={form.full_name}
              onChange={e => setForm({ ...form, full_name: e.target.value })} placeholder="Nombre y apellido" />
          </div>
          <div>
            <div className="label">Contraseña (mín. 6)</div>
            <input className="input" type="text" required minLength={6} value={form.password}
              onChange={e => setForm({ ...form, password: e.target.value })} placeholder="contraseña inicial" />
          </div>
          <div>
            <div className="label">Operador WATI (opcional)</div>
            <input className="input" value={form.operator_name}
              onChange={e => setForm({ ...form, operator_name: e.target.value })} placeholder="nombre en WATI" />
          </div>
        </div>
        <div className="mt-4">
          <div className="label">Rol</div>
          <div className="flex flex-wrap gap-2">
            {ROLES.map(r => {
              const elevado = r.key !== 'asesor'
              const disabled = elevado && !isSuperAdmin
              return (
                <button key={r.key} type="button" disabled={disabled}
                  onClick={() => setForm({ ...form, role: r.key })}
                  title={disabled ? 'Solo un super-admin puede asignar este rol' : ''}
                  className={`px-3 py-1.5 rounded-full text-[12px] font-medium transition flex items-center gap-1.5 ${
                    form.role === r.key ? 'bg-deep text-bone' : 'bg-bone-200/60 text-muted hover:bg-bone-200'
                  } ${disabled ? 'opacity-40 cursor-not-allowed' : ''}`}>
                  <r.icon size={13} /> {r.label}
                </button>
              )
            })}
          </div>
        </div>
        {msg && <div className={`mt-4 text-[13px] ${msg.ok ? 'text-emerald-600' : 'text-rose-600'}`}>{msg.text}</div>}
        <div className="mt-5">
          <button disabled={busy} className="btn-primary flex items-center gap-1.5">
            <UserPlus size={15} /> {busy ? 'Creando…' : 'Crear usuario'}
          </button>
        </div>
      </form>

      {/* Listado */}
      <div className="card overflow-hidden shadow-soft">
        <table className="w-full text-sm">
          <thead className="bg-bone-100/70 text-[11px] uppercase tracking-[0.14em] text-muted">
            <tr>
              <th className="text-left px-5 py-3">Nombre</th>
              <th className="text-left px-5 py-3">Email</th>
              <th className="text-left px-5 py-3">Operador WATI</th>
              <th className="text-left px-5 py-3">Rol</th>
              <th className="text-left px-5 py-3">Estado</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} className="border-t border-border/60">
                <td className="px-5 py-3 font-medium text-deep">{u.full_name || '—'}</td>
                <td className="px-5 py-3 text-muted">{u.email}</td>
                <td className="px-5 py-3 text-muted">{u.operator_name || '—'}</td>
                <td className="px-5 py-3">
                  {isSuperAdmin ? (
                    <select value={u.role} onChange={e => cambiarRol(u, e.target.value)}
                      className="text-[12px] rounded-lg border border-border/60 px-2 py-1 bg-white">
                      {ROLES.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
                    </select>
                  ) : (
                    <span className={`chip ${roleClass(u.role)} px-2.5 py-1 rounded-full text-[11px] font-semibold`}>{roleLabel(u.role)}</span>
                  )}
                </td>
                <td className="px-5 py-3">
                  <button onClick={() => toggleActivo(u)}
                    className={`text-[11px] font-semibold px-2.5 py-1 rounded-full ${
                      u.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'
                    }`}>
                    {u.is_active ? 'Activo' : 'Inactivo'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
