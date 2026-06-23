-- Migración: agrega el rol "super_admin" al enum user_role y asciende al admin
-- principal. Idempotente. Correr en la DB de producción (Supabase).
--
-- En SQLite (local) no hace falta: el rol es texto libre y create_all lo maneja.

-- 1. Agregar el valor al enum (Postgres). IF NOT EXISTS evita error si ya está.
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'super_admin';

-- 2. Ascender al admin principal a super-admin (ajustá el email si corresponde).
--    Nota: en Postgres el nuevo valor del enum no puede usarse en la MISMA
--    transacción que el ALTER TYPE; correr este UPDATE por separado.
UPDATE public.users SET role = 'super_admin' WHERE email = 'admin@babilonia.com';
