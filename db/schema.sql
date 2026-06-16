-- Tomi · Babilonia — schema Supabase
-- Ejecutar en Supabase SQL editor sobre el proyecto donde ya existen `documents` y `n8n_chat_histories`.

-- ─── messages: ingesta tipada desde n8n (reemplaza el parseo de strings sobre n8n_chat_histories)
do $$ begin
  create type message_direction as enum ('cliente','asesor','bot','template');
exception when duplicate_object then null; end $$;

create table if not exists public.messages (
  id              bigserial primary key,
  wa_id           text not null,
  sender_name     text,
  operator_name   text,
  operator_email  text,
  direction       message_direction not null,
  message_type    text,
  template_name   text,
  content         text not null,
  event_type      text,
  wati_message_id text,
  created_at      timestamptz not null default now(),
  raw             jsonb
);
create index if not exists idx_messages_waid_at  on public.messages (wa_id, created_at desc);
create index if not exists idx_messages_oper_at  on public.messages (operator_name, created_at desc);
create index if not exists idx_messages_dir_at   on public.messages (direction, created_at desc);

-- ─── documents_meta: metadata de archivos cargados desde la plataforma
create table if not exists public.documents_meta (
  id           uuid primary key default gen_random_uuid(),
  file_name    text not null,
  source       text not null,
  uploaded_by  text,
  uploaded_at  timestamptz not null default now(),
  size_bytes   bigint,
  chunks       integer,
  status       text default 'ready',
  storage_path text
);
create index if not exists idx_docmeta_source on public.documents_meta (source);

-- ─── users: auth JWT propio de la plataforma (NO usa Supabase Auth)
do $$ begin
  create type user_role as enum ('admin','asesor');
exception when duplicate_object then null; end $$;

create table if not exists public.users (
  id            uuid primary key default gen_random_uuid(),
  email         text unique not null,
  password_hash text not null,
  full_name     text,
  role          user_role not null default 'asesor',
  operator_name text,
  is_active     boolean not null default true,
  created_at    timestamptz not null default now()
);
create index if not exists idx_users_operator on public.users (operator_name);

-- ─── agent_chats: historial del agente interno (chat de la plataforma con OpenAI)
create table if not exists public.agent_chats (
  id         bigserial primary key,
  user_id    uuid references public.users(id) on delete cascade,
  role       text not null,
  content    text,
  tool_calls jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_agentchats_user_at on public.agent_chats (user_id, created_at desc);

-- ─── tomi_locks: lock anti-doble-disparo del workflow tomi-trigger-23h
create table if not exists public.tomi_locks (
  wa_id       text primary key,
  acquired_at timestamptz not null default now()
);

-- ─── sandbox_feedback: loop de mejora (interacciones de Tomi + correcciones de admins)
-- También la crea SQLAlchemy (create_all); este DDL es para referencia / Supabase limpio.
create table if not exists public.sandbox_feedback (
  id                   bigserial primary key,
  pregunta             text not null,
  respuesta_tomi       text,
  respuesta_corregida  text,
  rating               text,                      -- good | bad | null
  status               text default 'pending',    -- pending | reviewed | promoted
  canal                text,                       -- sandbox | whatsapp | mail | discord
  source               text,                       -- plu3 | patrimonial | educacion | plu | plu4
  tags                 jsonb,
  user_email           text,
  reviewed_by          text,
  promoted_doc_source  text,
  created_at           timestamptz not null default now(),
  reviewed_at          timestamptz
);
create index if not exists idx_sandboxfb_status on public.sandbox_feedback (status, created_at desc);
create index if not exists idx_sandboxfb_rating on public.sandbox_feedback (rating);

-- ─── tomi_failed_dispatches: dead-letter de disparos del trigger 23h que fallaron
-- También la crea SQLAlchemy (create_all); DDL para referencia / Supabase limpio.
create table if not exists public.tomi_failed_dispatches (
  id                bigserial primary key,
  wa_id             text not null,
  sender_name       text,
  last_user_message text,
  reason            text,
  attempts          integer default 1,
  resolved          boolean default false,
  created_at        timestamptz not null default now(),
  last_attempt_at   timestamptz default now()
);
create index if not exists idx_faileddisp_pending on public.tomi_failed_dispatches (resolved, last_attempt_at desc);
create index if not exists idx_faileddisp_waid on public.tomi_failed_dispatches (wa_id);
