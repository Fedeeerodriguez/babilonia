-- Restauración del conocimiento RAG de Tomi
-- Proyecto Supabase: vpeeeeanqumeyemhdxta  (DOCUMENTS_DATABASE_URL del backend)
-- Tabla vector store: public.documents
--
-- Contexto: el 23/06/2026 una re-ingesta desde Google Drive truncó el 92% del
-- conocimiento (educacion 354k->10k chars, plu3 47k->8k, patrimonial 11k->5k).
-- auto y proteccion quedaron intactas. El backup public.documents_backup_20260623
-- tiene el estado sano completo (2680 chunks) CON los embeddings ya calculados.
--
-- Verificado (read-only) antes de escribir:
--   - id = nextval('documents_id_seq')  -> INSERT sin id funciona.
--   - El estado actual es subconjunto del backup -> no se pierde nada al restaurar.
--
-- Costo OpenAI: CERO (los embeddings vienen del backup).

-- 1) Backup de seguridad del estado actual
DROP TABLE IF EXISTS public.documents_backup_pre_restore_20260710;
CREATE TABLE public.documents_backup_pre_restore_20260710 AS
  SELECT * FROM public.documents;

-- 2) Restaurar las 3 categorías degradadas desde el backup del 23/06
DELETE FROM public.documents
  WHERE metadata->>'source' IN ('educacion','plu3','patrimonial');

INSERT INTO public.documents (content, metadata, embedding)
  SELECT content, metadata, embedding
  FROM public.documents_backup_20260623
  WHERE metadata->>'source' IN ('educacion','plu3','patrimonial');

-- 3) Verificar (esperado: ~2680 chunks totales)
SELECT metadata->>'source' AS source,
       count(*) AS chunks,
       sum(length(content)) AS chars
FROM public.documents
GROUP BY 1 ORDER BY 2 DESC;

-- Rollback (si algo sale mal):
--   DELETE FROM public.documents;
--   INSERT INTO public.documents (content, metadata, embedding)
--     SELECT content, metadata, embedding FROM public.documents_backup_pre_restore_20260710;
