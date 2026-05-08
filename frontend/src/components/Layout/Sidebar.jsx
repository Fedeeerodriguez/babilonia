import { NavLink } from 'react-router-dom'
import { LayoutGrid, MessagesSquare, Users, BookOpen, Bot, UserCog } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

const link = ({ isActive }) =>
  `group flex items-center gap-3 px-3 py-2 rounded-xl text-[13px] font-medium tracking-tight transition-all duration-200 ${
    isActive
      ? 'bg-deep text-bone shadow-soft'
      : 'text-deep/65 hover:bg-bone-200/60 hover:text-deep'
  }`

export default function Sidebar() {
  const { isAdmin } = useAuth()
  return (
    <aside className="w-60 shrink-0 border-r border-border/60 bg-white/30 backdrop-blur-sm
                      min-h-[calc(100vh-3rem)] py-5 px-3 flex flex-col">
      <div className="section-label !mt-0">Panel</div>
      <NavLink to="/dashboard" className={link}><LayoutGrid size={15} strokeWidth={1.8}/> Dashboard</NavLink>
      <NavLink to="/conversations" className={link}><MessagesSquare size={15} strokeWidth={1.8}/> Conversaciones</NavLink>
      <NavLink to="/advisors" className={link}><Users size={15} strokeWidth={1.8}/> Asesores</NavLink>

      <div className="section-label">Conocimiento</div>
      <NavLink to="/knowledge" className={link}><BookOpen size={15} strokeWidth={1.8}/> Documentos</NavLink>
      <NavLink to="/agent" className={link}><Bot size={15} strokeWidth={1.8}/> Tomi (chat)</NavLink>

      {isAdmin && (
        <>
          <div className="section-label">Administración</div>
          <NavLink to="/team" className={link}><UserCog size={15} strokeWidth={1.8}/> Usuarios</NavLink>
        </>
      )}

      <div className="mt-auto pt-6 px-3">
        <div className="text-[10px] tracking-[0.18em] uppercase text-muted/60 font-semibold">Babilonia v0.1</div>
        <div className="text-[10px] text-muted/50 mt-1 tracking-wide">Métricas · Conocimiento · Asistencia</div>
      </div>
    </aside>
  )
}
