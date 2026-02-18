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
  day int not null,
  title text,
  notes text,
  real_world_date date,
  hidden boolean default false
);

-- Keep day constraints in sync with Harptos festivals:
-- 1..30 for all months, plus 31 only for festival months.
alter table public.events
  drop constraint if exists events_day_check;

alter table public.events
  drop constraint if exists events_day_valid_check;

alter table public.events
  add constraint events_day_valid_check
  check (
    (day between 1 and 30)
    or (day = 31 and month in (1, 4, 7, 9, 11))
  );

-- Helpful index for day lookups
create index if not exists events_ymd_idx on public.events(year, month, day);

-- Atomically advance global Harptos date based on elapsed real days.
create or replace function public.advance_harptos_date_if_needed(
  default_year int,
  default_month int,
  default_day int,
  today date default current_date
)
returns jsonb
language plpgsql
as $$
declare
  cur jsonb;
  last_checked jsonb;
  y int;
  m int;
  d int;
  last_dt date;
  days_elapsed int;
  i int;
begin
  perform pg_advisory_xact_lock(hashtext('harptos_global_date'));

  select value into cur
  from public.state
  where key = 'current_date'
  limit 1;

  if cur is null then
    y := default_year;
    m := greatest(1, least(12, default_month));
    d := greatest(1, least(31, default_day));
    if d = 31 and m not in (1, 4, 7, 9, 11) then
      d := 30;
    end if;
    cur := jsonb_build_object('year', y, 'month', m, 'day', d);
    insert into public.state(key, value)
    values ('current_date', cur)
    on conflict (key) do update
      set value = excluded.value,
          updated_at = now();
  end if;

  y := coalesce((cur->>'year')::int, default_year);
  m := coalesce((cur->>'month')::int, default_month);
  d := coalesce((cur->>'day')::int, default_day);
  m := greatest(1, least(12, m));
  d := greatest(1, least(31, d));
  if d = 31 and m not in (1, 4, 7, 9, 11) then
    d := 30;
  end if;

  select value into last_checked
  from public.state
  where key = 'last_checked'
  limit 1;

  begin
    if last_checked is null then
      last_dt := today;
    else
      last_dt := (last_checked #>> '{}')::date;
    end if;
  exception
    when others then
      last_dt := today;
  end;

  days_elapsed := today - last_dt;

  if days_elapsed > 0 then
    for i in 1..days_elapsed loop
      if d = 31 then
        if m = 12 then
          y := y + 1;
          m := 1;
          d := 1;
        else
          m := m + 1;
          d := 1;
        end if;
      elsif d < 30 then
        d := d + 1;
      elsif d = 30 then
        if m in (1, 4, 7, 9, 11) then
          d := 31;
        elsif m = 12 then
          y := y + 1;
          m := 1;
          d := 1;
        else
          m := m + 1;
          d := 1;
        end if;
      else
        d := 1;
      end if;
    end loop;
  end if;

  cur := jsonb_build_object('year', y, 'month', m, 'day', d);

  insert into public.state(key, value)
  values ('current_date', cur)
  on conflict (key) do update
    set value = excluded.value,
        updated_at = now();

  insert into public.state(key, value)
  values ('last_checked', to_jsonb(today::text))
  on conflict (key) do update
    set value = excluded.value,
        updated_at = now();

  return cur;
end;
$$;
