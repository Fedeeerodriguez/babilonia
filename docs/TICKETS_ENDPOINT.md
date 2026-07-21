# Tickets personalizados — endpoint `crear-ticket`

Reemplaza los nodos crudos de Notion en n8n por **un endpoint del backend** que Tomi
llama como tool. El backend genera el `ticket_id` real y **asigna al admin encargado**.

## Endpoint
```
POST https://<backend>/api/tomi/crear-ticket
Header: X-Tomi-Key: <TOMI_INTERNAL_KEY>
Body (JSON):
{
  "descripcion": "Asesor pide número de cliente de Mario Aldama; no lo encuentra.",  // requerido
  "encargado": "Yans",              // Ceci | Yans | Anayanci | Jime
  "nombre_cliente": "Mario Aldama", // opcional
  "email": "asesor@x.com",          // opcional
  "telefono": "+52...",             // opcional
  "rol": "Asesor",                  // Asesor | Estudiante | Cliente Allianz | Prospecto
  "tipo": "Solicitud de Apoyo a Cliente",  // opcional (select de Notion)
  "prioridad": "media",             // baja | media | alta
  "medio": "Teléfono"               // Teléfono | Discord | Correo (opcional)
}
```
Respuesta:
```json
{ "ok": true, "ticket_id": "TCK-260721-3F9A", "encargado": "Yans",
  "url": "https://notion.so/...", "notion_page_id": "..." }
```

## Qué hace mejor que los nodos actuales
- **ticket_id real y único** (TCK-AAMMDD-XXXX), generado por el backend → nunca vacío ni duplicado.
- **Asignación real** al admin en el campo Notion **"Asignado a"** (Ceci/Yans/Anayanci/Jime).
- Mapea prioridad/tipo/rol/medio a los selects reales de "Tickets Babilonia".
- Un solo lugar para cambiar la lógica (backend), no 2 nodos duplicados en n8n.

## Cómo conectarlo en n8n (2 opciones)

### Opción A — como TOOL del agente (recomendada)
1. Agregá un nodo **HTTP Request Tool** llamado `crear_ticket_python`, conectado a
   `AGENTE SOPORTE TOMMY` (ai_tool), igual que `bases_datos_python`.
2. Config:
   - Method: POST · URL: `https://<backend>/api/tomi/crear-ticket`
   - Header `X-Tomi-Key`: la key.
   - Body (JSON) con los campos de arriba, usando `$fromAI(...)` para que el LLM los complete.
3. En el system prompt, en ESCALAMIENTO: "para crear un ticket, llamá a la tool
   `crear_ticket_python` con `encargado` = quien corresponde (Ceci/Yans/Anayanci/Jime) y
   una `descripcion` clara. La tool te devuelve el `ticket_id` REAL — usá ESE en tu respuesta,
   nunca inventes uno." Y quitá la parte de "ticket_id = TCK- + 6 digitos".
4. Podés **eliminar** los nodos `Switch Ticket`, `Date & Time Allianz/General`,
   `TICKET ALLIANZ` y `ticket general` (ya no se usan).

### Opción B — como nodo HTTP en el flujo (mínimo cambio)
Reemplazá los 2 nodos de Notion (`TICKET ALLIANZ` / `ticket general`) por un solo
**HTTP Request** a `/api/tomi/crear-ticket`, pasando `output.ticket` como `descripcion`
y derivando `encargado` del `comando`/contenido. Menos limpio que A.

## Pendiente / notas
- **Tickets Allianz** (`NOTION_DB_TICKETS_ALLIANZ`) NO es accesible por la integración del
  backend (object_not_found). Por ahora TODO entra a **Tickets Babilonia**; para diferenciar
  un caso Allianz, usar `tipo="Trámite Allianz"`. Si querés que los Allianz vayan a su base,
  compartí esa base de Notion con la integración del backend.
- Campo **"Asignado a"** (Select: Ceci/Yans/Anayanci/Jime) creado en Tickets Babilonia.
