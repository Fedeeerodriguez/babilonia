-- Migración: memoria de clasificación de usuarios para Tomi (sub-agente clasificador).
-- Reemplaza la "memoria" del AI Agent2 de n8n: en vez de recordar en el contexto del
-- chat, persiste la clasificación (asesor/estudiante/cliente/prospecto) por user_id.
-- Idempotente. Correr en la DB de producción (Supabase).
--
-- En SQLite (local) SQLAlchemy no crea esta tabla (es SQL crudo en clasificador.py),
-- así que correr el equivalente local si se quiere caché en dev.

create table if not exists public.tomi_clasificaciones (
  user_id        text primary key,            -- chat_id Telegram / wa_id WhatsApp
  email          text,
  comando_1      text not null,               -- "registrado" | "no registrado"
  comando_2      text not null,               -- "asesor" | "estudiante" | "cliente" | "prospecto"
  user_nombre    text,
  notion_page_id text,                         -- page de Notion donde se encontró (si aplica)
  data           jsonb,                        -- snapshot de los datos del usuario en Notion
  updated_at     timestamptz not null default now()
);

create index if not exists idx_tomi_clasif_email on public.tomi_clasificaciones (email);
