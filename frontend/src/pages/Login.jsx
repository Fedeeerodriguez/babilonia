import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import Logo from '../components/Logo'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const nav = useNavigate()

  const submit = async (e) => {
    e.preventDefault(); setErr(''); setLoading(true)
    try { await login(email, password); nav('/dashboard') }
    catch (e) { setErr(e.response?.data?.detail || 'Error al iniciar sesión') }
    finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.1fr_1fr] bg-bg">
      <div className="hidden lg:flex flex-col justify-between p-14 xl:p-20 bg-deep text-bone relative overflow-hidden">
        <div className="absolute -top-40 -left-40 w-[500px] h-[500px] rounded-full bg-cobalt/25 blur-3xl"/>
        <div className="absolute -bottom-40 -right-20 w-[420px] h-[420px] rounded-full bg-cobalt-700/30 blur-3xl"/>
        <div className="absolute inset-0 opacity-[0.04]"
          style={{ backgroundImage: 'radial-gradient(circle at 30% 30%, white 1px, transparent 1px)', backgroundSize: '22px 22px' }}/>

        <div className="relative z-10"><Logo size="md" color="bone" /></div>

        <div className="relative z-10 max-w-lg animate-slide-up">
          <div className="text-[12px] uppercase tracking-[0.22em] text-cobalt-300 font-semibold mb-5">
            Métricas · Conocimiento · Asistencia
          </div>
          <h1 className="hero-title text-6xl xl:text-7xl mb-6">
            Tomi <br/><span className="text-cobalt-300">para Allianz.</span>
          </h1>
          <p className="text-bone/70 text-lg leading-relaxed font-light max-w-md">
            La plataforma interna del equipo de asesores: métricas en vivo, conversaciones, base de conocimiento.
          </p>
        </div>

        <div className="relative z-10 text-bone/40 text-[11px] tracking-[0.15em] uppercase">
          © Babilonia · Tomi
        </div>
      </div>

      <div className="flex flex-col justify-center px-6 py-12 lg:px-20">
        <div className="w-full max-w-sm mx-auto animate-fade-in">
          <div className="lg:hidden mb-10"><Logo size="md" tagline /></div>

          <div className="mb-10">
            <h2 className="font-display text-4xl font-bold tracking-[-0.035em] text-deep mb-3">Iniciar sesión</h2>
            <p className="text-muted text-[15px] font-light">Bienvenido. Accedé a tu panel.</p>
          </div>

          <form onSubmit={submit} className="space-y-5">
            <div>
              <label className="label">Email</label>
              <input className="input" type="email" value={email} onChange={(e)=>setEmail(e.target.value)} required autoFocus/>
            </div>
            <div>
              <label className="label">Contraseña</label>
              <input className="input" type="password" value={password} onChange={(e)=>setPassword(e.target.value)} required/>
            </div>
            {err && <div className="text-danger text-sm">{err}</div>}
            <button disabled={loading} className="btn-primary btn-lg w-full">
              {loading ? 'Ingresando...' : <>Continuar <ArrowRight size={16}/></>}
            </button>
          </form>

          <div className="text-center mt-8 text-[13px] text-muted">
            ¿Sos nuevo? <Link to="/register" className="text-cobalt-700 font-medium hover:text-cobalt-600">Crear cuenta →</Link>
          </div>
        </div>
      </div>
    </div>
  )
}
