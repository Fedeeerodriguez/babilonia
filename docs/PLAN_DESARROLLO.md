# Plan de desarrollo — Tomi · Babilonia

> Estado vivo del proyecto. El PDF `Plan_Babilonia_Tomi.pdf` es la versión para el cliente
> (cronograma de 8 semanas); este archivo es la versión técnica que seguimos los devs.

## Dónde estamos (junio 2026)

La mayoría de las herramientas de Tomi ya están construidas (pólizas, cobranzas, productos,
asesores, renovaciones, siniestros, comisiones, bonos, Notion scanner, clasificador, analítica,
sub-agente de memorias, seed demo). El trabajo restante es **completar cálculos faltantes,
cargar contenido y sumar canales**.

## Backlog priorizado

### 🧰 Etapa 1 — Herramientas / cálculos (Semana 3)
- [x] **Días de atraso de un cliente/póliza** → `POST /api/tomi/dias-atraso`
      (servicio `notion_client.dias_de_atraso`). Devuelve agregado: máx. días, pólizas
      en atraso, monto faltante total y detalle por póliza.
- [ ] Conectar el nuevo endpoint como tool en el sub-agente `bases_datos` de n8n.
- [ ] Resumen de cartera "en riesgo" por asesor (cobranzas > 15 días).

### 📚 Etapa 1 — Conocimiento a cargar (Semana 4)
- [ ] FAQ de pólizas → chunks + embeddings (`source: plu`/`patrimonial`).
- [ ] Accesos del curso / cómo entrar (Calendly + plataforma) → `source: educacion`.
- [ ] Cómo reprogramar reuniones (Calendly).

### 📧 Etapa 1 — Canales nuevos (Semanas 5–6)
- [ ] Lector de correos Allianz (pólizas y tickets) → ingest a `messages`.
- [ ] Conectar Tomi a Gmail.
- [ ] Conectar Tomi a Discord.

### 📊 Etapa 2 — Auto-mejora (Semanas 7–8)
- [ ] Panel de control: consultas atendidas, resueltas, trabadas, feedback.
- [ ] Job semanal: IA analiza el panel y entrega informe de sugerencias (humano aprueba).

## 💡 Ideas innovadoras propuestas

1. **Tomi proactivo de cobranzas.** Job diario que, usando `dias_de_atraso`, detecta clientes
   que cruzan umbrales (7/15/30 días) y le avisa al asesor por WhatsApp antes de que el cliente
   se queje — convierte a Tomi de reactivo a preventivo.
2. **Confianza y "no sé" honesto.** Que cada respuesta del agente incluya un nivel de confianza
   y, si está bajo, escale a un humano en vez de inventar. Reduce alucinaciones en datos sensibles.
3. **Memoria de feedback como dataset.** Las correcciones del sandbox (Semana 1) se guardan como
   pares pregunta/respuesta-corregida y alimentan los embeddings → Tomi mejora con cada corrección.
4. **Resumen semanal por asesor.** Cada lunes, Tomi le manda a cada asesor su foto: renovaciones
   próximas, cobranzas en riesgo, comisiones del mes, puntos de convención.
5. **Simulador de escenarios.** "¿Cuánto cobro si cierro estas 3 pólizas?" usando comisiones/bonos
   ya cargados — herramienta de venta, no solo de consulta.
6. **Detección de duplicados/inconsistencias cross-source** (ya hay base en `validaciones.py`):
   exponerla como alerta accionable en el panel de Etapa 2.

## Convenciones técnicas
- Endpoints del agente bajo `/api/tomi/*`, auth por header `X-Tomi-Key`.
- Lógica determinística en `services/tomi/*` (sin LLM intermedio que elija filtros mal).
- Property names de Notion configurables / tolerantes a variantes (ej. "Días de atraso"
  vs "Días de Atraso Actuales").
