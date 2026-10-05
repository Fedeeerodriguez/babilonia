# Avisos de citas canceladas / reagendadas (asesor + centinela)

Cuando un prospecto **cancela o reagenda** su llamada, Tomi avisa por WhatsApp **directo al
asesor y al centinela** (quien entra a la reunión; en Notion figura como *Cerrador*) con los
datos del prospecto para que lo contacten. **Ceci y Jime no intervienen.**

- El asesor recibe el aviso **siempre**.
- El centinela recibe el aviso **cuando la cita tiene uno** (si es la misma persona, va un solo aviso).

## Cómo funciona

| Disparador | Qué lo activa | Código |
|---|---|---|
| **Vigilante** | Una automatización externa (Calendly → Notion) marca la cita como `Cancelada` o `Reagendada` en la base *Eventos Calendly*. Tomi revisa esa base cada 10 min. | `avisos_citas.escanear()` |
| **WhatsApp** | El prospecto le escribe a Tommy que no puede ir o quiere cambiar la cita. | `POST /api/tomi/aviso-cita` |

- **Reagendada:** si el prospecto ya eligió nueva fecha, el aviso la incluye; si no, manda el link para reagendar.
- **Citas pasadas** (más de 1 día) no se avisan.
- **Sin duplicados:** cada aviso se registra en `tomi_avisos_citas` (único por cita + motivo + rol). Con varios workers solo uno lo envía. Si WATI falla, se reintenta hasta 3 veces.
- Por WhatsApp se avisa **una vez por día y por cita**, aunque el prospecto escriba varias veces.

## 1. Plantilla de WATI (crear y esperar aprobación)

WhatsApp exige plantilla aprobada para los mensajes que inicia la empresa.
En WATI → **Broadcast → Template Messages → New Template Message**:

- **Nombre:** `aviso_cita_prospecto`
- **Categoría:** Utility
- **Idioma:** Spanish (MEX)
- **Pie (footer, opcional):** `Mensaje automático de Tommy`
- **Botones:** ninguno
- **Cuerpo** (las variables deben llamarse exactamente así; nunca dos variables pegadas, WhatsApp lo rechaza):

```
Hola {{nombre}} 👋 Te aviso que tu prospecto {{prospecto}} ya {{accion}} su cita del {{fecha_cita}}.

{{detalle}}

📱 Teléfono: {{telefono}}
✉️ Correo: {{correo}}

Contáctalo directamente para coordinar. — Tommy, Babilonia
```

Ejemplo real de cómo se completa:
> Hola Kevin 👋 Te aviso que tu prospecto Monica Ake ya **canceló** su cita del **mar 06/10 10:00 h**.
> Link para reagendar: https://calendly.com/reschedulings/…
> 📱 Teléfono: +52 … · ✉️ Correo: …

## 2. Variables de entorno (servicio `babilonia`, backend)

| Variable | Valor | Para qué |
|---|---|---|
| `WATI_SERVER` | la misma que usa n8n (`https://live-mt-server.wati.io/…`) | envío por WhatsApp |
| `WATI_TOKEN` | el token de la API de WATI | envío por WhatsApp |
| `WATI_PLANTILLA_CITA` | `aviso_cita_prospecto` | nombre de la plantilla |
| `AVISOS_CITAS_ACTIVO` | `1` para encender el vigilante (default `0`) | |
| `AVISOS_CITAS_DRY_RUN` | `1` = simula sin enviar (default). `0` = envía de verdad | |
| `AVISOS_CITAS_INTERVALO_MIN` | `10` | cada cuántos minutos revisa |
| `AVISOS_CITAS_VENTANA_HORAS` | `6` | solo citas modificadas en las últimas N horas |

### Verificar la plantilla apenas WATI la apruebe
Mandá la plantilla real con datos de ejemplo a tu propio WhatsApp:

```
POST https://plataforma-babilonia-babilonia.qfsutf.easypanel.host/api/tomi/avisos-citas/prueba
Header:  X-Tomi-Key: <clave interna>
Body:    {"numero": "5219991234567"}
```

Tiene que llegarte el mensaje con "Kevin", "Monica Ake (PRUEBA)", "canceló", etc., cada valor en
su lugar. Si alguna variable aparece vacía o WATI responde error de parámetros, el nombre de
esa variable no coincide con la plantilla.

**Contrato:** los nombres de las variables viven en `VARIABLES_PLANTILLA`
(`backend/app/services/tomi/avisos_citas.py`). Si se cambia uno, hay que cambiarlo también en la
plantilla de WATI y en este documento. El test `test_contrato_plantilla_codigo_y_documentacion`
falla si no coinciden.

### Puesta en marcha recomendada
1. Deploy con `AVISOS_CITAS_ACTIVO=1` y `AVISOS_CITAS_DRY_RUN=1`. Durante 1–2 días revisar
   `GET /api/tomi/avisos-citas` (header `X-Tomi-Key`): muestra qué se **habría** mandado.
2. Con la plantilla aprobada en WATI → `AVISOS_CITAS_DRY_RUN=0` y redeploy.

## 3. n8n — que Tommy avise cuando el prospecto se lo pide

**a) Nueva herramienta** en el agente `AGENTE SOPORTE TOMMY` (nodo *HTTP Request Tool*, igual que
`crear_ticket_python`), conectada como `ai_tool`:

- **Nombre:** `aviso_cita_python`
- **Description:** `Usala cuando el usuario diga que no puede asistir, que quiere cancelar o cambiar/reagendar su cita o llamada con un asesor. Avisa DIRECTO a su asesor y a su centinela y devuelve la fecha de la cita, el link para reagendar y los nombres. NO crees ticket ni escales a Ceci/Jime por esto.`
- **Method:** POST · **URL:** `https://plataforma-babilonia-babilonia.qfsutf.easypanel.host/api/tomi/aviso-cita`
- **Headers:** `X-Tomi-Key` = (la misma clave que usan las otras tools)
- **Body parameters:**

| Name | Value |
|---|---|
| `wa_id` | `{{ String($('Edit Fields1').first().json.message.chat.id) }}` |
| `mensaje` | `{{ $fromAI('mensaje', 'Lo que dijo el usuario sobre su cita', 'string') }}` |
| `correo` | `{{ $fromAI('correo', 'Correo con el que agendó, solo si lo dio. Si no, vacío.', 'string') }}` |

**b) Regla en el System Message** (agregarla en el ÁRBOL DE DECISIÓN, aplica a cualquier rol,
incluidos prospectos):

```
CITA / LLAMADA CON ASESOR — cancelar o reagendar (cualquier rol, también prospectos):
Si el usuario dice que no puede asistir, que quiere cancelar o cambiar su cita/llamada,
llama a aviso_cita_python. NO crees ticket y NO escales a Ceci ni a Jime.
- Si encontrado=true: confirmale que ya avisaste a su asesor {asesor} (y a {centinela}
  si viene) y que lo van a contactar; compartile el link_reagendar para que elija nueva fecha.
- Si encontrado=false: pedile el correo con el que agendó y volvé a llamar a la tool con ese correo.
```

## 4. Operación

- Ver avisos: `GET /api/tomi/avisos-citas?limit=50` (estados: `enviado`, `simulado`, `error`, `sin_numero`).
- Correr el vigilante a mano: `POST /api/tomi/avisos-citas/escanear?ventana_horas=24`.
- `sin_numero`: al asesor/centinela le falta el teléfono en Notion (Directorio/CRM Asesores) → completarlo.
