-- State key/value (current_date, last_checked)
create table if not exists public.state (
  key text primary key,
  value jsonb,
  updated_at timestamptz default now()
);

-- Events per day
create table if not exists public.events (
  id uuid primary key,
  year int not null,
  month int not null check (month between 1 and 12),
  day int not null check (day between 1 and 30),
  title text,
  notes text,
  real_world_date date,
  hidden boolean default false
);

-- Helpful index for day lookups
create index if not exists events_ymd_idx on public.events(year, month, day);