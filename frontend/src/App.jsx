import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Conversations from './pages/Conversations'
import Advisors from './pages/Advisors'
import Knowledge from './pages/Knowledge'
import AgentChat from './pages/AgentChat'
import Analytics from './pages/Analytics'
import Team from './pages/Team'
import Layout from './components/Layout/Layout'
import ProtectedRoute from './components/Layout/ProtectedRoute'

const P = ({ children, fullWidth, ...p }) => (
  <ProtectedRoute {...p}><Layout fullWidth={fullWidth}>{children}</Layout></ProtectedRoute>
)

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/dashboard" element={<P><Dashboard /></P>} />
      <Route path="/conversations" element={<P><Conversations /></P>} />
      <Route path="/advisors" element={<P><Advisors /></P>} />
      <Route path="/knowledge" element={<P><Knowledge /></P>} />
      <Route path="/agent" element={<P><AgentChat /></P>} />
      <Route path="/analytics" element={<P><Analytics /></P>} />
      <Route path="/team" element={<P requireAdmin><Team /></P>} />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
