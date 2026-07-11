# Plan de Actualizaciones — Tomi · Babilonia

> Origen: análisis del sandbox (`sandbox_feedback`, últimas 2 semanas al 08/07/2026).
> Tasa de aprobación actual: **74% good** · 14% mejorable · 1% bad.
> Objetivo: **≥90% good** cerrando las causas raíz detectadas.

## Dónde vive cada cosa (arquitectura)

| Destino | Qué se toca | Cómo se aplica |
|---|---|---|
| **n8n** (`tomi unificado`) | System prompt conversacional de Tommy | Pegar bloque en el nodo del agente (ver `PROMPT_TOMI_CONVERSACIONAL.md`) |
| **RAG** (`documents` pgvector) | Conocimiento (Liga Babilonia, productos, grabaciones) | Subir doc desde la página **Knowledge** (ver `CONOCIMIENTO_LIGA_BABILONIA.md`) |
| **Repo backend** | Bugs, telemetría, promoción de feedback | PR normal |
| **Babilonia (Jime/Ceci)** | Valores exactos que solo ellos saben | Pedido de info (ver `../MENSAJE_PEDIDO_BABILONIA` — pendiente) |

---

## Leyenda
🤖 = dev (no depende de nadie) · 👤 = depende de Babilonia · 🟢 alto impacto · 🟡 medio

---

## FASE 0 — Entregables base (HECHO en esta ronda) 🤖
- [x] Extracción y análisis de las 31 correcciones del sandbox.
- [x] `CONOCIMIENTO_LIGA_BABILONIA.md` — borrador del doc para el RAG (con lo ya confirmado + huecos marcados `[CONFIRMAR BABILONIA]`).
- [x] `PROMPT_TOMI_CONVERSACIONAL.md` — bloque de reglas para pegar en n8n.
- [x] Este plan.

## FASE 1 — Prompt conversacional en n8n 🤖 🟢
Cambios que NO necesitan datos nuevos. Reducen ~50% de los "mejorable".
- [ ] 1.1 **Anti-reintroducción**: presentarse solo en el 1er mensaje; ante "ok/gracias/emoji" no reiniciar.
- [ ] 1.2 **Memoria de hilo**: no perder de qué se venía hablando (usar historial).
- [ ] 1.3 **No responder a solo-emoji**: si el mensaje es únicamente un emoji, Tommy no contesta.
- [ ] 1.4 **Ticket-first**: lista de temas que van directo a ticket (Ceci/Jime) sin loop de preguntas.
- [ ] 1.5 **No interferir con humano activo**: si un asesor respondió recién (`chat_states.ultimo_mensaje_asesor`), Tommy se calla.
- **Aplicación**: pegar `PROMPT_TOMI_CONVERSACIONAL.md` en el system prompt del workflow.

## FASE 2 — Cargar conocimiento al RAG 🤖 (parcial 👤) 🟢
- [ ] 2.1 Subir `CONOCIMIENTO_LIGA_BABILONIA.md` a Knowledge (lo ya confirmado por Jimena).
- [ ] 2.2 Completar los `[CONFIRMAR BABILONIA]` cuando lleguen (umbrales del semáforo, link de acompañamiento, catálogo).
- [ ] 2.3 Re-subir versión final.

## FASE 3 — Cerrar el loop de feedback 🤖 🟢
- [ ] 3.1 Script/flujo para **promover correcciones aprobadas** (`promoted_doc_source`) al RAG.
- [ ] 3.2 Promover las 31 correcciones históricas ya revisadas.
- [ ] 3.3 Dejar el flujo recurrente (cada corrección revisada → candidato a doc).

## FASE 4 — Bugs y robustez 🤖 🟡
- [ ] 4.1 **Respuestas vacías** (ids 181/182, `respuesta_tomi=""`): investigar causa + fallback anti-vacío.
- [ ] 4.2 Parsing multimedia ("mensaje no llegó completo" cuando sí había contenido).
- [ ] 4.3 Poblar `tomi_conversaciones` (telemetría: intents/latencia/tokens) — hoy 0 filas.

## FASE 5 — Datos de Babilonia 👤
Ver mensaje de pedido. Bloquea 2.2. Enviar cuanto antes.
- [ ] 5.1 Reglas Liga completas (semáforo umbrales, comodines, vidas, misiones, avanzados).
- [ ] 5.2 Links correctos (acompañamiento, recuperación 404).
- [ ] 5.3 Catálogo productos + política grabaciones + routing tickets.

## FASE 6 — Medición 🤖
- [ ] 6.1 Re-correr el análisis del sandbox 2 semanas después.
- [ ] 6.2 Comparar KPIs (% good, quejas Liga → 0, promovidos/semana > 0).

---

## Ruta crítica
```
FASE 0 (hecho) → FASE 1 (n8n, ya) ┐
              → FASE 3 (loop, ya)  ├→ FASE 6 (medir)
FASE 5 (Babilonia) → FASE 2.2 ─────┘
```
El único freno externo es **FASE 5**. Todo lo demás corre sin ellos.
