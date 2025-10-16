
-- Minimal schema for 'items' table
create extension if not exists "uuid-ossp";

create table if not exists public.items (
  id uuid primary key default uuid_generate_v4(),
  title text not null,
  body text,
  tags text[],
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Simple update trigger for updated_at
create or replace function public.set_updated_at() returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end
$$;

drop trigger if exists trg_items_updated_at on public.items;
create trigger trg_items_updated_at before update on public.items
for each row execute procedure public.set_updated_at();

-- RLS is OFF by default in this starter for private Posit Cloud usage.
-- For broader sharing, enable RLS and write owner-scoped policies.
