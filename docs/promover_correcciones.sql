-- Cerrar el loop de feedback: marcar las correcciones ya consolidadas en
-- CONOCIMIENTO_LIGA_BABILONIA.md como promovidas, para no re-procesarlas.
--
-- Contexto: al 08/07/2026 había 31 correcciones revisadas (respuesta_corregida no vacía)
-- y 0 promovidas (promoted_doc_source = NULL). Este script las estampa como promovidas
-- al doc de conocimiento que se sube al RAG.
--
-- REVISAR antes de correr. Hacer backup / correr el SELECT primero.

-- 1) Previsualizar qué se va a marcar (correr esto primero)
SELECT id, created_at, rating, left(pregunta, 60) AS q
FROM sandbox_feedback
WHERE promoted_doc_source IS NULL
  AND respuesta_corregida IS NOT NULL
  AND length(trim(respuesta_corregida)) > 0
ORDER BY created_at DESC;

-- 2) Estampar como promovidas (descomentar para ejecutar)
-- UPDATE sandbox_feedback
-- SET promoted_doc_source = 'CONOCIMIENTO_LIGA_BABILONIA.md'
-- WHERE promoted_doc_source IS NULL
--   AND respuesta_corregida IS NOT NULL
--   AND length(trim(respuesta_corregida)) > 0;

-- 3) Limpieza de los 2 registros basura (respuesta vacía por el bug del logger WATI)
--    Opcional: marcarlos como descartados en vez de dejarlos como 'bad'.
-- UPDATE sandbox_feedback
-- SET status = 'descartado'
-- WHERE coalesce(trim(respuesta_tomi), '') = '' AND source = 'wati';
