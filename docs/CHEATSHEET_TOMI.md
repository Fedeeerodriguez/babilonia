# ⚡ Cheat-sheet Tomi — acceso rápido: pregunta → dónde está el dato → qué responder

Guía de consulta veloz para Tommy y el equipo. Cada fila: **qué pregunta el usuario →
qué fuente/modo usar → campos clave → nota**. (Ver el mapa completo en
docs/MAPA_CONOCIMIENTO_TOMI.md.)

## Identidad (¿quién es?)
| Pregunta | Fuente | Responder |
|---|---|---|
| Cualquier consulta con un email | Clasificador (Notion: Asesores→Estudiantes→Clientes) | Si es asesor Y cliente → queda **asesor** (prioridad fija) |
| No dio email | Clasificador | Pedir el correo antes de dar datos (`necesita_email`) |

## Cliente
| Pregunta | Modo/fuente | Campos clave |
|---|---|---|
| "¿cuánto debo? / mi atraso / covranza" | `cobranzas` (por póliza o email) | usar **`Días de Atraso Actuales`** (vivo), Monto Faltante, Semáforo, Estado de Cobranza |
| "ya pagué / me regularicé" | — | NO contradecir con el número; puede tardar 24-48h. Pedir comprobante, ofrecer escalar a Yans |
| "estado de mi póliza / mis pólizas" | `polizas` | Producto, Estado, Prima, Conducto, Fecha de cobro, Asesor |
| "¿qué es OptiMaxx X?" | RAG (memorias) por `clave` | ver desambiguación de productos |
| "agendar cita con mi asesor" | Calendly | link https://calendly.com/asesores-atomicos/acompanamiento |
| "¿bonos / puntos?" (cliente) | — | Aclarar: bonos/puntos son del **programa de asesores**, no aplican al cliente |

## Asesor
| Pregunta | Modo/fuente | Campos clave |
|---|---|---|
| "mi cartera / mis clientes" | `cartera` (requiere email_asesor) | clientes únicos + fondos |
| "cobranza del cliente póliza X" | `cobranzas` | titular real de esa póliza (no el asesor) |
| "mi DAF / número de agente" | `daf` | número de agente, cédula, estado activo |
| "mis renovaciones / siniestros" | intents `renovacion`/`siniestro` (por póliza o email_asesor) | **si vacío → decir "no hay cargado", NO desviar a póliza** |
| "mis comisiones (de una póliza)" | intent `comision` (por póliza) | idem: honestidad si no hay datos |
| "bonos / puntos de convención / mes 13" | programa de asesores | bases dedicadas; hoy pueden estar sin cargar → decirlo |

## Estudiante / Alumno
| Pregunta | Fuente | Campos clave |
|---|---|---|
| "mis cursos / progreso / asistencias" | perfil estudiante (Notion) | Plan, Meses en programa, Curso teórico, Asistencias Zoom |
| "no entro al curso / zoom" | — | dar link mágico; si es problema técnico, escalar con ticket |

## Reglas transversales (siempre)
- **No inventar productos:** ante "¿tienen seguro de X?", consultar catálogo `productos`; si no está, NO existe.
- **No inventar datos:** si una base está vacía o no hay registro, decirlo con honestidad y ofrecer escalar.
- **Días de atraso:** siempre el campo **vivo** (`Días de Atraso Actuales`), nunca el guardado.
- **Escalar con ticket** cuando el usuario reporta un problema que Tommy no puede resolver con datos.
