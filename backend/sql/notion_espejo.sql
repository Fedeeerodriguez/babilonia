-- Espejo de Notion (proyecto Supabase ESPEJO_DATABASE_URL). Idempotente: se puede correr de nuevo.
-- Una tabla genérica para todas las bases NOTION_DB_*; Tommy y el gestor leen de acá en vez de Notion.
-- Ver docs/ESPEJO_NOTION.md.

create schema if not exists notion_espejo;
create extension if not exists pg_trgm;
create extension if not exists vector;

-- Una fila por base de Notion.
create table if not exists notion_espejo.bases (
  slug               text primary key,          -- emisiones, cobranzas, clientes_auto… (NOTION_DB_<SLUG>)
  db_id              text not null unique,
  titulo             text,
  esquema            jsonb not null default '{}'::jsonb,   -- {propiedad: tipo}
  relaciones         jsonb not null default '{}'::jsonb,   -- {propiedad: slug destino}
  filas              int not null default 0,
  ultimo_edit_visto  timestamptz,                -- el last_edited_time más nuevo ya copiado
  ultimo_sync        timestamptz,                -- última corrida (completa o incremental) sin error
  ultima_carga       timestamptz,                -- última carga completa
  estado             text not null default 'pendiente',    -- pendiente | ok | error
  error              text,
  actualizado_en     timestamptz not null default now()
);

-- Una fila por página (registro) de cualquier base.
create table if not exists notion_espejo.paginas (
  page_id            uuid primary key,
  base_slug          text not null references notion_espejo.bases(slug),
  titulo             text,
  props              jsonb not null,            -- aplanadas (mismo formato que notion_client._flatten_props)
  props_raw          jsonb,                     -- como las devuelve Notion
  texto_busqueda     text,                      -- todo el texto plano, para búsquedas aproximadas
  url                text,
  created_time       timestamptz,
  last_edited_time   timestamptz,
  archivada          boolean not null default false,
  -- Para el bidireccional futuro (plataforma de asesores ↔ Notion).
  origen             text not null default 'notion',
  version            int not null default 1,
  hash_props         text,
  synced_at          timestamptz not null default now()
);
create index if not exists paginas_base_idx on notion_espejo.paginas (base_slug) where not archivada;
create index if not exists paginas_edit_idx on notion_espejo.paginas (base_slug, last_edited_time desc);
create index if not exists paginas_props_idx on notion_espejo.paginas using gin (props jsonb_path_ops);
create index if not exists paginas_texto_trgm on notion_espejo.paginas using gin (texto_busqueda gin_trgm_ops);

-- Relaciones entre páginas, para unir localmente (en vez de pages.retrieve por cada id).
create table if not exists notion_espejo.relaciones (
  desde_page   uuid not null references notion_espejo.paginas(page_id) on delete cascade,
  propiedad    text not null,
  hacia_page   uuid not null,
  primary key (desde_page, propiedad, hacia_page)
);
create index if not exists relaciones_hacia_idx on notion_espejo.relaciones (hacia_page);

-- Páginas que avisó el webhook de Notion y falta volver a leer.
create table if not exists notion_espejo.pendientes (
  page_id      uuid primary key,
  evento       text,
  recibido_en  timestamptz not null default now(),
  intentos     int not null default 0
);

-- Modo sombra: lo que respondió Notion vs. lo que respondió el espejo, cuando no coinciden.
create table if not exists notion_espejo.diferencias (
  id           bigserial primary key,
  consulta     text not null,
  parametros   jsonb,
  notion       jsonb,
  espejo       jsonb,
  creado_en    timestamptz not null default now()
);

-- Ajustes del espejo (ej. el token de verificación del webhook de Notion).
create table if not exists notion_espejo.ajustes (
  clave        text primary key,
  valor        text,
  actualizado_en timestamptz not null default now()
);

-- Corridas del sincronizador (para el monitoreo y para no repetir lo de la cuota de Gmail).
create table if not exists notion_espejo.corridas (
  id           bigserial primary key,
  tipo         text not null,                  -- completa | incremental | webhook | reconciliacion
  base_slug    text,
  inicio       timestamptz not null default now(),
  fin          timestamptz,
  paginas      int not null default 0,
  pedidos      int not null default 0,         -- pedidos a la API de Notion
  error        text
);
create index if not exists corridas_inicio_idx on notion_espejo.corridas (inicio desc);

-- Capa vectorial del espejo (solo bases semánticas: productos, tickets, siniestros, contenido).
create table if not exists notion_espejo.documentos (
  id           bigserial primary key,
  page_id      uuid references notion_espejo.paginas(page_id) on delete cascade,
  content      text not null,
  metadata     jsonb not null default '{}'::jsonb,
  embedding    vector(1536),
  hash_props   text
);
create index if not exists documentos_page_idx on notion_espejo.documentos (page_id);

create or replace function notion_espejo.match_espejo(query_embedding vector(1536), match_count int default 5,
                                                      filter jsonb default '{}'::jsonb)
returns table (id bigint, page_id uuid, content text, metadata jsonb, similarity float)
language sql stable as $$
  select d.id, d.page_id, d.content, d.metadata, 1 - (d.embedding <=> query_embedding) as similarity
  from notion_espejo.documentos d
  where d.metadata @> filter and d.embedding is not null
  order by d.embedding <=> query_embedding
  limit match_count;
$$;

-- Solo el backend (rol postgres) lee y escribe: nada expuesto por la API pública de Supabase.
do $$
declare t text;
begin
  foreach t in array array['bases','paginas','relaciones','pendientes','diferencias','corridas','documentos','ajustes'] loop
    execute format('alter table notion_espejo.%I enable row level security', t);
  end loop;
end $$;
revoke all on schema notion_espejo from anon, authenticated;
revoke all on all tables in schema notion_espejo from anon, authenticated;
