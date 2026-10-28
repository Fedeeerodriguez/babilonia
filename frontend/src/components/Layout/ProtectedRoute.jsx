import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

export default function ProtectedRoute({ children, requireAdmin = false }) {
  const { user, loading, isAdmin } = useAuth()
  const location = useLocation()
  if (loading) return <div className="p-8 text-muted">Cargando...</div>
  // El login vuelve a esta página (ej. el link de un aviso: /tickets-allianz?ticket=7).
  if (!user) return <Navigate to="/login" replace state={{ desde: location.pathname + location.search }} />
  if (requireAdmin && !isAdmin) return <Navigate to="/dashboard" replace />
  return children
}
