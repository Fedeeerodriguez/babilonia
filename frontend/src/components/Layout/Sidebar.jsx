import { NavLink } from 'react-router-dom'
import { LayoutGrid, MessagesSquare, Users, BookOpen, Bot, UserCog, BarChart3, FlaskConical } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

const link = ({ isActive }) =>
  `group flex items-center gap-3 px-3 py-2 rounded-xl text-[13px] font-medium tracking-tight transition-all duration-200 ${
    isActive
      ? 'bg-deep text-bone shadow-soft'
      : 'text-deep/65 hover:bg-bone-200/60 hover:text-deep'
  }`

export default function Sidebar({ mobileOpen = false, onClose = () => {} }) {
  const { isAdmin } = useAuth()
  return (
    <>
      {/* Overlay (solo mobile/tablet cuando el drawer está abierto) */}
      <div
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-deep/40 backdrop-blur-sm transition-opacity duration-300 lg:hidden ${
          mobileOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        aria-hidden="true"
      />

      <aside
        className={`w-60 shrink-0 border-r border-border/60 bg-white/95 lg:bg-white/30 backdrop-blur-sm
                    py-5 px-3 flex flex-col
                    fixed inset-y-0 left-0 z-50 h-screen transform transition-transform duration-300
                    lg:static lg:z-auto lg:h-auto lg:min-h-[calc(100vh-3rem)] lg:translate-x-0
                    ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className="section-label !mt-0">Panel</div>
        <NavLink to="/dashboard" onClick={onClose} className={link}><LayoutGrid size={15} strokeWidth={1.8}/> Dashboard</NavLink>
        <NavLink to="/conversations" onClick={onClose} className={link}><MessagesSquare size={15} strokeWidth={1.8}/> Conversaciones</NavLink>
        <NavLink to="/advisors" onClick={onClose} className={link}><Users size={15} strokeWidth={1.8}/> Asesores</NavLink>

        <div className="section-label">Conocimiento</div>
        <NavLink to="/knowledge" onClick={onClose} className={link}><BookOpen size={15} strokeWidth={1.8}/> Documentos</NavLink>
        <NavLink to="/agent" onClick={onClose} className={link}><Bot size={15} strokeWidth={1.8}/> Tomi (chat)</NavLink>
        <NavLink to="/analytics" onClick={onClose} className={link}><BarChart3 size={15} strokeWidth={1.8}/> Analítica</NavLink>
        <NavLink to="/sandbox" onClick={onClose} className={link}><FlaskConical size={15} strokeWidth={1.8}/> Sandbox</NavLink>

        {isAdmin && (
          <>
            <div className="section-label">Administración</div>
            <NavLink to="/team" onClick={onClose} className={link}><UserCog size={15} strokeWidth={1.8}/> Usuarios</NavLink>
          </>
        )}

        <div className="mt-auto pt-6 px-3">
          <div className="text-[10px] tracking-[0.18em] uppercase text-muted/60 font-semibold">Babilonia v0.1</div>
          <div className="text-[10px] text-muted/50 mt-1 tracking-wide">Métricas · Conocimiento · Asistencia</div>
        </div>
      </aside>
    </>
  )
}
