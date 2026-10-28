import axios from 'axios'

// Cliente para la API del GESTOR DE TICKETS ALLIANZ, que vive FUERA de Tomi (proyecto aparte,
// Tommi-ticket-allianz). Se configura por variable de entorno del frontend:
//   VITE_TICKETS_ALLIANZ_API -> URL base del servicio Allianz (p. ej. https://allianz.tudominio)
// La API acepta la misma sesión de Tomi (la valida con el SECRET_KEY de Tomi): no hay token fijo
// dentro del panel. Si no está seteada la URL, la sección muestra un aviso de "no configurada".
const baseURL = import.meta.env.VITE_TICKETS_ALLIANZ_API || ''

export const ticketsAllianzConfigurada = Boolean(baseURL)

const tapi = axios.create({ baseURL })

tapi.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Sesión vencida o inválida → al login (igual que el resto de Tomi).
tapi.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (location.pathname !== '/login') {
        // Después del login vuelve a esta página (ej. el link de un aviso a un ticket).
        try { sessionStorage.setItem('volver', location.pathname + location.search) } catch { /* sin storage */ }
        location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)

// Quién hace cada cosa, para la bitácora del ticket (aprobó la guía, abrió el trámite…).
export function usuarioActual() {
  try {
    const u = JSON.parse(localStorage.getItem('user') || '{}')
    return (u.full_name || u.operator_name || u.email || 'panel').slice(0, 40)
  } catch {
    return 'panel'
  }
}

export default tapi
