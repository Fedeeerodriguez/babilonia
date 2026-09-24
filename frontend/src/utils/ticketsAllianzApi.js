import axios from 'axios'

// Cliente para la API del GESTOR DE TICKETS ALLIANZ, que vive FUERA de Tomi (proyecto aparte,
// Tommi-ticket-allianz). Se configura por variables de entorno del frontend:
//   VITE_TICKETS_ALLIANZ_API   -> URL base del servicio Allianz (p. ej. https://allianz.tudominio)
//   VITE_TICKETS_ALLIANZ_TOKEN -> token opcional (si el API lo exige)
// Si no está seteada la URL, la sección muestra un aviso de "no configurada".
const baseURL = import.meta.env.VITE_TICKETS_ALLIANZ_API || ''
const token = import.meta.env.VITE_TICKETS_ALLIANZ_TOKEN || ''

export const ticketsAllianzConfigurada = Boolean(baseURL)

const tapi = axios.create({
  baseURL,
  headers: token ? { Authorization: `Bearer ${token}` } : {},
})

export default tapi
