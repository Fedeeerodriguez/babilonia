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
