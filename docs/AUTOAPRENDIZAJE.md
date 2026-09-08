# Auto-aprendizaje de Tommy (feedback de asesores → directrices)

Tommy aprende a ser mejor asistente a partir del feedback que le dan **los asesores** en el
chat. Cuando un asesor lo corrige, Tommy: repregunta para profundizar → decide si es un
feedback **técnico y generalizable** → si lo es, lo convierte en una **directriz** que se
aplica a **todas** las conversaciones (clientes y asesores).

Solo aprende de **asesores** (no de clientes). Es **auditable y reversible**.

## Flujo

```
mensaje de un ASESOR
  → POST /api/tomi/aprender-feedback  (publico=asesor)
      1. pre-filtro barato: ¿parece corrección? (si no → no hace nada)
      2. analizador LLM (gpt-4.1-mini):
           ¿es feedback técnico y GENERALIZABLE?
           ¿falta contexto? → devuelve una PREGUNTA (Tommy repregunta)
           ¿ya está cubierto / contradice una activa? → refuerza / manda a revisión
      3. destila una DIRECTRIZ corta e imperativa + confianza (0-100)
      4. confianza ≥ 80 → ACTIVA (aplica a todos) + alerta Telegram
         confianza < 80 → PROPUESTA (cola de aprobación)
         dedupe por hash → no duplica; refuerza (veces_reforzada++)
  → responde al asesor con `responder` (la repregunta o el acuse de recibo)

cada conversación (cualquiera)
  → GET /api/tomi/directrices  → bloque de directrices ACTIVAS
  → se inyecta en el systemMessage del agente  → afecta a TODOS
```

## Endpoints (backend, header `X-Tomi-Key`)

| Método | Ruta | Para qué |
|---|---|---|
| POST | `/api/tomi/aprender-feedback` | Procesa el mensaje del asesor. Body: `mensaje`, `respuesta_tomi`, `publico`, `user_email`, `historial`, `continuacion`. Devuelve `responder` (lo que Tommy dice) + qué aprendió. |
| GET | `/api/tomi/directrices?ambito=todos` | Bloque de directrices activas para inyectar en el prompt. |
| GET | `/api/tomi/directrices/admin?estado=` | Lista para gestión (propuesta/activa/rechazada/desactivada). |
| POST | `/api/tomi/directrices/{id}/aprobar` | Activa una propuesta (aplica a todos). |
| POST | `/api/tomi/directrices/{id}/rechazar` | Descarta una propuesta. |
| POST | `/api/tomi/directrices/{id}/desactivar` | **Rollback**: desactiva una activa. |

## Guardarraíles

- Solo **asesores** (gate por `publico`).
- Auto-activa **solo alta confianza** (≥ `APRENDIZAJE_UMBRAL_AUTO`, default 80); el resto queda a aprobación.
- Lo que **contradice** una directriz activa → SIEMPRE a revisión humana (no auto-activa).
- **Alerta a Telegram** (reusa `TELEGRAM_ALERT_*`) por cada directriz nueva/activada.
- **Dedupe** por hash normalizado → no acumula duplicados; refuerza los repetidos.
- Todo queda en `tomi_directrices` (auditable) y se puede **revertir con 1 request**.

## Wiring en n8n (pendiente de aplicar)

1. **Aprender** — en el flujo del responder, cuando `publico == asesor`, agregar un nodo HTTP
   `POST /api/tomi/aprender-feedback` con el mensaje del asesor, la respuesta previa de Tommy y
   el `historial`. Si la respuesta trae `responder`, usar ESE texto como respuesta al asesor.
   Si `accion == "preguntar"`, en el siguiente turno del asesor mandar `continuacion: true`.
2. **Aplicar** — al inicio de cada conversación, nodo HTTP `GET /api/tomi/directrices` y
   anteponer `{{ bloque }}` al `systemMessage` del AGENTE SOPORTE TOMMY.

## Config (env)

- `APRENDIZAJE_UMBRAL_AUTO` — confianza mínima (0-100) para auto-activar. Default 80.
- Reusa `OPENAI_API_KEY` / `OPENAI_CHAT_MODEL` y `TELEGRAM_ALERT_*` del backend principal.
