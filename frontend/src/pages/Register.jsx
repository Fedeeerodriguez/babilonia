import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import Logo from '../components/Logo'

export default function Register() {
  const [form, setForm] = useState({ full_name:'', email:'', operator_name:'', password:'' })
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const { register, login } = useAuth()
  const nav = useNavigate()
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault(); setErr(''); setLoading(true)
    try {
      await register({ ...form, role: 'asesor' })
      await login(form.email, form.password)
      nav('/dashboard')
    } catch (e) { setErr(e.response?.data?.detail || 'Error') }
    finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen grid place-items-center px-6 py-12 bg-bg">
      <div className="w-full max-w-md animate-fade-in">
        <div className="text-center mb-8"><Logo size="md" tagline className="mx-auto" /></div>
        <div className="card p-10 shadow-card">
          <h1 className="font-display text-3xl font-bold tracking-[-0.035em] mb-2">Crear cuenta</h1>
          <p className="text-muted text-[15px] font-light mb-8">El primer usuario será administrador.</p>
          <form onSubmit={submit} className="space-y-3">
            <div><label className="label">Nombre completo</label><input className="input" value={form.full_name} onChange={set('full_name')} required/></div>
            <div><label className="label">Email</label><input className="input" type="email" value={form.email} onChange={set('email')} required/></div>
            <div><label className="label">Nombre como operador en WATI</label><input className="input" value={form.operator_name} onChange={set('operator_name')} placeholder="ej: María González"/></div>
            <div><label className="label">Contraseña</label><input className="input" type="password" value={form.password} onChange={set('password')} required minLength={6}/></div>
            {err && <div className="text-danger text-sm">{err}</div>}
            <button disabled={loading} className="btn-primary w-full mt-2">
              {loading ? 'Creando...' : <>Crear cuenta <ArrowRight size={16}/></>}
            </button>
          </form>
        </div>
        <div className="text-center mt-6 text-sm text-muted">
          ¿Ya tenés cuenta? <Link to="/login" className="text-cobalt-700 font-medium hover:underline">Iniciá sesión</Link>
        </div>
      </div>
    </div>
  )
}
