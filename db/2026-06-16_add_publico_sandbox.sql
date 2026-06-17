-- Migración: agrega `publico` a sandbox_feedback (Semana 1 — revisión por tipo de público)
-- y soporta el rating intermedio 'mejorable'. Idempotente: se puede correr varias veces.
--
-- Correr en la DB de producción (Supabase) además de schema.sql.
-- El rating 'mejorable' no requiere DDL (la columna `rating` es text libre); este script
-- solo agrega el campo `publico` y su índice.

alter table public.sandbox_feedback
  add column if not exists publico text;   -- cliente | asesor | prospecto | estudiante | otro

create index if not exists idx_sandboxfb_publico
  on public.sandbox_feedback (publico);
