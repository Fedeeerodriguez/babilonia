import { useEffect, useState } from 'react'
import api from '../utils/api'

export default function Team() {
  const [users, setUsers] = useState([])
  useEffect(() => { api.get('/api/users').then(r => setUsers(r.data)).catch(()=>{}) }, [])
  return (
    <div className="max-w-4xl mx-auto animate-fade-in">
      <div className="hero-eyebrow">Administración</div>
      <h1 className="hero-title text-4xl text-deep mb-8">Usuarios</h1>
      <div className="card overflow-hidden shadow-soft">
        <table className="w-full text-sm">
          <thead className="bg-bone-100/70 text-[11px] uppercase tracking-[0.14em] text-muted">
            <tr>
              <th className="text-left px-5 py-3">Nombre</th>
              <th className="text-left px-5 py-3">Email</th>
              <th className="text-left px-5 py-3">Operador WATI</th>
              <th className="text-left px-5 py-3">Rol</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} className="border-t border-border/60">
                <td className="px-5 py-3 font-medium text-deep">{u.full_name || '—'}</td>
                <td className="px-5 py-3 text-muted">{u.email}</td>
                <td className="px-5 py-3 text-muted">{u.operator_name || '—'}</td>
                <td className="px-5 py-3"><span className="chip-cobalt">{u.role}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
