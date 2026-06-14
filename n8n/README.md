# Workflows n8n — Tomi · Babilonia

Tres workflows componen el sistema completo de mensajería + handoff de 23h:

| # | Workflow | Archivo | Trigger | Para qué sirve |
|---|---|---|---|---|
| 1 | **actualizacion contexto wati** | [`actualizacion_contexto_wati.json`](actualizacion_contexto_wati.json) | Webhook desde WATI | Ingesta: cada mensaje (cliente/asesor/template) entra acá. Escribe en `n8n_chat_histories` (memoria de Tomi) **y** en `messages` (analytics). |
| 2 | **tomi unificado** | (existente, NO incluido) | Webhook bridge (ver #3) | El agente AI que arma la respuesta y la manda a WATI. Tu workflow actual. |
| 3 | **tomi-trigger-23h** | [`tomi_trigger_23h.json`](tomi_trigger_23h.json) | Schedule cada 5 min | Detecta conversaciones donde el último mensaje del cliente tiene ≥23h sin respuesta y dispara a Tomi vía HTTP. |
| 3b | **bridge para tomi unificado** | [`tomi_webhook_entry.json`](tomi_webhook_entry.json) | (snippet, no es un workflow completo) | Snippet con un Webhook trigger + Set + Respond para pegar AL INICIO del workflow `tomi unificado`. Es la puerta de entrada por la que el #3 dispara. |

## Loop de feedback del sandbox

| Workflow | Archivo | Trigger | Para qué sirve |
|---|---|---|---|
| **Log feedback sandbox** | [`feedback_log_sandbox.json`](feedback_log_sandbox.json) | Manual (snippet) | Registra cada interacción de Tomi en `/api/feedback/log` para que los admins la revisen/corrijan desde la página **Sandbox** de la plataforma. |

**Cómo integrarlo en el flujo del sandbox:**

1. Importá `feedback_log_sandbox.json` (sirve para probar el endpoint con el botón "Execute workflow").
2. Asegurate de tener las env vars en n8n: `TOMI_API_URL` (ej. `https://api.babilonia.ai`) y `TOMI_INTERNAL_KEY` (igual a la del backend).
3. Copiá el nodo **`Registrar feedback (Tomi)`** (HTTP Request) y pegalo en tu workflow `tomi unificado`, **después** del nodo que produce la respuesta final de Tomi.
4. Conectá la salida del agente a ese nodo y ajustá el `jsonBody` para que tome los campos reales:
   - `pregunta` → el texto del usuario (ej. `{{ $('Mapear payload').item.json.last_user_message }}`)
   - `respuesta_tomi` → la respuesta generada (ej. `{{ $json.output }}`)
   - `canal` → `"sandbox"` mientras entrenan; `"whatsapp"` en producción
   - `source` → opcional, el área (`plu3`, `patrimonial`, etc.)
   - `user_email` → opcional, el email del que escribió
5. El nodo es **fire-and-forget**: ponelo en una rama paralela para no demorar la respuesta a WATI.

Una vez registradas, las interacciones aparecen en **Sandbox** (sidebar de la plataforma). Ahí el admin las califica 👍/👎, escribe la respuesta corregida y, al aprobarlas, las **promueve** al vector store (`documents`) con el mismo `source` que consume Tomi → aprende al instante.

## Orden de instalación

### 0. Crear tablas en Supabase

Ejecutá [`../db/schema.sql`](../db/schema.sql) en el SQL editor de Supabase. Eso crea:
- `messages` — analytics tipados.
- `tomi_locks` — lock anti-doble-disparo.
- `documents_meta`, `users`, `agent_chats` — para la plataforma.

Verificá:
```sql
select count(*) from public.messages;
select count(*) from public.tomi_locks;
```

### 1. Credencial Supabase Postgres en n8n

Si el workflow viejo `actualizacion contexto wati` usa una credencial Postgres que **no apunta a Supabase** (caso típico: apunta al Postgres interno de n8n, donde vive `n8n_chat_histories`), creá una credencial **nueva**:

- Settings → Credentials → New → Postgres
- Nombre: `Supabase Postgres`
- Connection string: el de Supabase (Project Settings → Database → Connection string → URI o Pooler).

Guardá el ID de credencial — lo vas a usar en los pasos 2 y 4.

### 2. Importar `actualizacion_contexto_wati.json`

Reemplaza al workflow viejo. **Ojo:**
- Los 3 nodos `Guardar mensaje cliente1`/`asesor1`/`automático` siguen escribiendo a `n8n_chat_histories` con la **credencial vieja** (la que ya funcionaba).
- Los 3 nodos nuevos `messages: cliente`/`asesor`/`template` deben usar la **credencial Supabase Postgres** (paso 1). Editá cada uno y cambiá la credencial.

### 3. Pegar el bridge en `tomi unificado`

Abrí tu workflow `tomi unificado`. En un área vacía del canvas, pegá el JSON de [`tomi_webhook_entry.json`](tomi_webhook_entry.json) (Ctrl+V dentro del editor).

Te van a aparecer 3 nodos nuevos:
- `Webhook Tomi (trigger 23h)` — escucha en `/webhook/tomi-responder`.
- `Mapear payload` — extrae `wa_id`, `sender_name`, `last_user_message`, etc.
- `Responder 200 OK al trigger` — responde inmediatamente al workflow #3 para que no quede colgado.

Conectá la salida de `Mapear payload` al primer nodo del agente AI de Tomi (el que antes recibía la entrada del trigger viejo de WATI). El agente debe tomar el texto del usuario desde `$json.last_user_message`.

Si tu Tomi tiene otro trigger (por ejemplo el webhook directo de WATI), podés dejarlos en paralelo: ambos convergen en el mismo agente.

### 4. Importar `tomi_trigger_23h.json`

Antes de activarlo:
1. En los **3 nodos Postgres** (`Limpiar locks viejos`, `Buscar candidatos`, `Liberar lock (fallo disparo)`), reemplazá la credencial por **Supabase Postgres** (paso 1). En el JSON quedó como placeholder `REEMPLAZAR_POR_CREDENCIAL_SUPABASE`.
2. En el nodo `Disparar Tomi`, ajustá la URL si tu n8n no es `n8n.babilonia.ai`. La URL correcta la ves en el workflow `tomi unificado` → click en el nodo `Webhook Tomi (trigger 23h)` → "Test URL" / "Production URL".
3. Activá el workflow.

> **Anti-doble-disparo (P1):** el nodo `Buscar candidatos` ahora hace un *claim atómico* en
> `tomi_locks` (`INSERT ... ON CONFLICT DO NOTHING RETURNING`), así dos ejecuciones simultáneas
> no pueden disparar la misma conversación dos veces. `Limpiar locks viejos` borra locks de más
> de 2h (por si un disparo quedó colgado), y si `Disparar Tomi` falla tras 3 reintentos, la rama
> de error libera el lock para reintentar en el próximo tick. Requiere la tabla `tomi_locks`
> (ya está en `db/schema.sql`).

## Cómo verificar que funciona

```sql
-- 1. Backdatear el último mensaje cliente de un wa_id de prueba para que se vea ≥23h viejo
UPDATE messages
SET created_at = NOW() - INTERVAL '23 hours 5 minutes'
WHERE id = (
  SELECT id FROM messages
  WHERE wa_id = '<TU_WA_ID_DE_PRUEBA>' AND direction = 'cliente'
  ORDER BY created_at DESC LIMIT 1
);
```

En el siguiente tick (≤5 min):
- En la pestaña Executions de `tomi-trigger-23h` ves una ejecución exitosa.
- En `tomi_locks` aparece tu wa_id.
- El workflow `tomi unificado` se ejecuta vía el webhook.
- Cuando Tomi manda la respuesta a WATI y vuelve por `actualizacion contexto wati`, en `messages` aparece la fila con `direction='bot'` (o `'asesor'` si Tomi figura como operador).
- En el siguiente tick, esa conversación **no** vuelve a aparecer (porque ya hay un mensaje posterior al del cliente).

## Reglas de oro del handoff

> **Tomi responde si y solo si el último mensaje del cliente tiene ≥23h y no existe ningún mensaje posterior en esa conversación.**

Esto cubre todos los casos:

| Escenario | Resultado |
|---|---|
| Cliente escribe, nadie responde 23h | Tomi responde |
| Cliente escribe, asesor responde a las 5h | Tomi se queda callado (hay mensaje del asesor después) |
| Tomi ya respondió, asesor toma el control | Tomi se queda callado (hay mensaje del asesor después) |
| Asesor responde, cliente no vuelve a escribir | Tomi se queda callado (no hay un nuevo mensaje del cliente) |
| Cliente vuelve a escribir | Cuenta nueva: si pasan 23h sin respuesta, Tomi entra |
| Cliente escribió hace >24h | Tomi NO dispara (ventana WhatsApp cerrada — solo templates) |

No hace falta un flag "Tomi muted" — la condición sale sola del orden cronológico de mensajes.
