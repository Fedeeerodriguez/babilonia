# 🗺️ MAPA DE CONOCIMIENTO DE TOMMY — dónde vive cada cosa y cómo llegar

> **Para qué sirve este documento:** es la "red de pensamiento" y las "vías de
> dirección" de los sub-agentes. Antes de buscar información, un agente (humano o LLM)
> mira este mapa para saber **QUÉ fuente tiene la respuesta** y **CÓMO filtrarla**.
> Si agregás/movés conocimiento, actualizá este mapa PRIMERO.

---

## 1. Arquitectura mental (3 capas)

```
Usuario (WhatsApp/Telegram)
        │
        ▼
[1] CLASIFICADOR  ──────────────►  ¿quién es? asesor / estudiante / cliente / prospecto
     clasificador.py                (por email → Notion: Asesores→Estudiantes→Clientes)
        │
        ▼
[2] AGENTE PRINCIPAL (Tommy, LLM)  ─►  decide a qué sub-agente delegar
        │
        ├─► [3a] SUB-AGENTE MEMORIAS   → CONOCIMIENTO (qué es un producto, cómo funciona)
        │        agente_memorias.py         Fuente: RAG / Supabase pgvector `documents`
        │
        └─► [3b] SUB-AGENTE BASES DATOS → DATOS VIVOS (este cliente, esta póliza, este pago)
                 bases_datos.py             Fuente: Notion (26 bases)
```

**Regla de oro de ruteo:**
- Pregunta de **CONCEPTO / “qué es / cómo funciona / diferencia entre”** → **MEMORIAS (RAG)**.
- Pregunta de **UN CASO CONCRETO** (un cliente, una póliza, un pago, un turno, un ticket)
  → **BASES DE DATOS (Notion)**.
- Si el mensaje trae **email / póliza (PLU3-123) / nombre propio** → casi siempre BASES DATOS.

---

## 2. VÍA A — CONOCIMIENTO (RAG / Supabase pgvector `documents`)

Proyecto Supabase RAG: `vpeeeeanqumeyemhdxta` · tabla `documents (id, content, metadata, embedding)`
· función de búsqueda `match_documents(query_embedding, match_count, filter)` (`metadata @> filter`).

### 2.1 Cómo está ORDENADO (metadata — usar para filtrar)
Cada chunk tiene:

| Clave metadata | Valores | Para qué filtrar |
|---|---|---|
| `clave` | `PLU3`, `OP3D`, `OPPT`, `SVIP`, `VIPP`, `AUIN` | **filtro más preciso: un producto exacto** |
| `categoria` | `ahorro`, `inversion`, `proteccion`, `seguro_general`, `liga`, `academia`, `feedback`, `indice` | filtrar por familia |
| `producto` | "OptiMaxx Plus", "OptiMaxx Educación", … | legible |
| `doc_tipo` | `ficha_curada` (concisa, autoritativa) · `conocimiento_producto` (PDF/resumen) · `proceso_liga` · `formacion` · `feedback` · `indice` | priorizar `ficha_curada` para desambiguar |
| `source` | `productos` (fichas curadas), `plu3`,`educacion`,`patrimonial`,`auto`,`proteccion` (legado) | compat. histórica |

> **Preferí `clave` para rutear.** Es la única llave unificada que existe TANTO en las
> fichas curadas (`source=productos`) como en los chunks viejos de PDF. Filtrar por
> `source` sola **NO** trae las fichas curadas nuevas.

### 2.2 Árbol de decisión de PRODUCTOS (la confusión #1 del bot)

```
¿Preguntan por "OptiMaxx" a secas?  → PEDIR cuál. NO asumir.
        │
        ├─ ahorro / retiro propio / deducir impuestos / PPR ......... PLU3  (OptiMaxx Plus)
        ├─ ahorro para el hijo / educación / universidad ............ OP3D  (OptiMaxx Educación)
        ├─ invertir un capital / pago fuerte / fideicomiso .......... OPPT  (OptiMaxx Patrimonial)
        ├─ inversión alta / dólares / euros / renta variable ....... SVIP  (OptiMaxx Elite)
        └─ "cuánto me pagan si fallezco" / cobertura de vida ....... VIPP  (OptiMaxx Protección)

Regla madre:
  PLUS + EDUCACIÓN  = ahorro con primas programadas
  PATRIMONIAL + ELITE = inversión de un capital
  PROTECCIÓN         = seguro de vida puro (NO ahorra)
```
Detalle completo por producto: [docs/productos/](productos/) (una ficha por producto)
y [docs/CONOCIMIENTO_PRODUCTOS_DESAMBIGUACION.md](CONOCIMIENTO_PRODUCTOS_DESAMBIGUACION.md).

### 2.3 Otros conocimientos en el RAG (no-producto)
- `categoria=liga` → reglas de la Liga Babilonia (semáforo, reingreso, roles). Doc fuente:
  [docs/CONOCIMIENTO_LIGA_BABILONIA.md](CONOCIMIENTO_LIGA_BABILONIA.md).
- `categoria=academia` → cursos/módulos/academia. Doc: [docs/CONOCIMIENTO_ACADEMIA_PRODUCTOS.md](CONOCIMIENTO_ACADEMIA_PRODUCTOS.md).

### 2.4 Qué FALTA en el RAG (si el agente no encuentra → escalar, no inventar)
- ⬜ SGMM (GMMI), Residencial (HOFP), Rentas Privadas, Ejecutivo → no hay Condiciones Generales cargadas.
- ⬜ Datos de proceso: Nivel 2/comisión con centinela, reset de contraseña del portal,
  link de reagendar Calendly → pedir a Jime (no están en Allianz).

---

## 3. VÍA B — DATOS VIVOS (Notion, sub-agente `bases_datos`)

Se llega por **regex** (email / póliza / nombre) + **keywords de intención**. Cada intención
apunta a una base concreta. Variables en `backend/.env` (`NOTION_DB_*`).

### 3.1 Ruteo por intención → base Notion

| Si el mensaje trae… | Intención | Base Notion (`NOTION_DB_*`) | Devuelve |
|---|---|---|---|
| email / póliza / nombre de cliente | perfil | CLIENTES + EMISIONES | quién es, sus pólizas |
| "pago, saldo, cuota, vencimiento, debo" | cobranza | **COBRANZAS** | días de atraso **VIVO** (`Días de Atraso Actuales`, NO el guardado) |
| "siniestro, denuncia, trámite, queja, endoso" | tickets | TICKETS_ALLIANZ / TICKETS_BABILONIA / SINIESTROS | estado del trámite |
| "turno, agenda, cita, reunión, calendly" | calendly | EVENTOS_CALENDLY | próximos turnos |
| "número/clave de agente, cédula, DAF" | daf | **DAF** | credenciales del agente |
| "venden, ofrecen, existe el seguro, catálogo" | productos | **PRODUCTOS** (catálogo real) | productos que SÍ existen (anti-invención) |
| "comisión, bono, convención, puntos" | comisiones | COMISIONES_AGENTES, BONOS_AGENTES, BONOS_PROMOTORIA, MES_13_PLU3, PUNTOS_CONVENCION | liquidaciones del agente |
| "renovación" | renovaciones | RENOVACIONES | pólizas a renovar |
| cartera de un asesor / por producto | cartera | CLIENTES_{PLU3,AUTO,PATRIMONIAL,EDUCACIONAL,GMM,RENTAS_PRIVADAS,RESIDENCIAL,PROTECCION,ELITE,PPR}, PORTAFOLIOS, MIGRACION_CARTERA | clientes de esa cartera |

### 3.2 Reglas críticas de datos
- **Cobranza / días de atraso:** SIEMPRE leer `Días de Atraso Actuales` (fórmula, viva),
  nunca `Días de atraso` (número guardado que queda viejo). Helper: `notion_client.pick_dias_atraso()`.
- Si el cliente dice **"ya pagué / me regularicé"**: NO contradecir con el número (el sistema
  tarda 24-48 h en reflejarlo). Pedir comprobante y ofrecer escalar a Yans (cobranza).
- **Productos:** ante "¿tienen seguro de X?", consultar la base **PRODUCTOS** y responder solo
  con lo que existe. NO inventar (ej. "seguro de mascotas" no existe).

---

## 4. VÍAS DE DIRECCIÓN (resumen rápido — "si… entonces…")

```
si el usuario NO dio email todavía ................. pedir email (clasificador → necesita_email)
si pregunta "qué es / diferencia / cómo funciona" .. RAG (filtrar por clave del producto)
si nombra OptiMaxx sin apellido ................... pedir cuál (ver árbol §2.2)
si trae póliza PLU3-xxxx / email / nombre ......... Notion (bases_datos §3.1)
si habla de plata/pago/atraso ..................... COBRANZAS (campo VIVO §3.2)
si dice "ya pagué" ................................ empatía + comprobante + escalar, NO el número
si pregunta "¿tienen seguro de X?" ................ base PRODUCTOS (no inventar)
si es siniestro/trámite/queja ..................... TICKETS_/SINIESTROS
si es turno/agenda ................................ EVENTOS_CALENDLY
si el RAG no trae nada relevante .................. escalar a humano, NO inventar
```

---

## 5. Dónde vive el código (para mantenimiento)

| Pieza | Archivo |
|---|---|
| Clasificador de usuario | `backend/app/services/tomi/clasificador.py` |
| Sub-agente MEMORIAS (RAG) | `backend/app/services/tomi/agente_memorias.py` + `memorias.py` + `memorias_bd.py` |
| Sub-agente BASES DATOS (Notion) | `backend/app/services/tomi/bases_datos.py` |
| Cliente Notion + helpers (atraso, etc.) | `backend/app/services/tomi/notion_client.py` |
| Ingesta de conocimiento al RAG | `backend/scripts/ingest_productos_rag.py` |
| Fichas de producto (fuente del RAG) | `docs/productos/*.md` |
| Prompt del agente principal | `docs/PROMPT_TOMMY_SYSTEM_v4.6.md` (se aplica en n8n) |

> **La taxonomía del RAG (clave/categoria/producto/doc_tipo) y las CATEGORIAS/KEYWORDS de
> `memorias.py` deben coincidir con este mapa.** Si cambiás uno, cambiá el otro.

---

## 6. Acceso rápido y capacidades nuevas (actualización)

- **Cheat-sheet operativo:** [docs/CHEATSHEET_TOMI.md](CHEATSHEET_TOMI.md) — tabla veloz
  "pregunta → fuente → qué responder". También cargado en el RAG (`doc_tipo=cheatsheet`).
- **Ruteo tolerante a typos:** `bases_datos._detectar_intents` normaliza acentos y reconoce
  errores comunes (covranza, atrazo, comiciones, vono, ajendar…).
- **Categorías nuevas por intent** (`bases_datos.consultar` + `informe.py`): `renovacion`,
  `siniestro`, `comision` — se filtran por póliza o email del asesor. Sus bases pueden estar
  **vacías**: en ese caso el informe agrega una advertencia `sin_datos_categoria` y el agente
  responde con honestidad (NO desvía a la póliza ni inventa).
- **Bonos / puntos / convención:** conceptos del **programa de asesores**, no aplican a
  clientes. Requieren la clave del agente (no se exponen crudos para no filtrar entre asesores).
