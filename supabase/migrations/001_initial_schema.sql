-- LEX ASSOCIÉS — première structure Supabase
-- Les mots de passe restent gérés par Supabase Auth.
create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  name text not null default '',
  role text not null default 'member' check (role in ('member','editor','admin','owner')),
  suspended boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.contents (
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  title text not null,
  category text not null default '',
  status text not null default 'draft' check (status in ('draft','published','archived')),
  payload jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table if not exists public.orders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  status text not null default 'new',
  total integer not null default 0,
  lines jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.order_updates (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  admin_id uuid not null references auth.users(id),
  status text not null,
  note text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  name text, email text, phone text, subject text, body text,
  status text not null default 'new',
  created_at timestamptz not null default now()
);

create table if not exists public.newsletter (
  email text primary key,
  name text,
  interests text,
  created_at timestamptz not null default now()
);

create table if not exists public.event_registrations (
  user_id uuid references auth.users(id) on delete cascade,
  content_id uuid not null references public.contents(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, content_id)
);

create table if not exists public.enrollments (
  user_id uuid references auth.users(id) on delete cascade,
  content_id uuid not null references public.contents(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, content_id)
);

create table if not exists public.progress (
  user_id uuid references auth.users(id) on delete cascade,
  content_id uuid not null references public.contents(id) on delete cascade,
  module_id text not null,
  completed_at timestamptz,
  primary key (user_id, content_id, module_id)
);

create table if not exists public.visits (
  id uuid primary key default gen_random_uuid(),
  visitor text not null, session text not null, page text not null,
  event text not null default 'view', target text not null default '',
  seconds integer not null default 0,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;
alter table public.contents enable row level security;
alter table public.orders enable row level security;
alter table public.order_updates enable row level security;
alter table public.messages enable row level security;
alter table public.newsletter enable row level security;
alter table public.event_registrations enable row level security;
alter table public.enrollments enable row level security;
alter table public.progress enable row level security;
alter table public.visits enable row level security;

-- Lecture publique des contenus publiés. Les écritures seront réservées à l'administration.
create policy "published contents are public" on public.contents for select using (status = 'published');
create policy "users read own profile" on public.profiles for select using (auth.uid() = id);
create policy "users update own profile" on public.profiles for update using (auth.uid() = id);
create policy "users read own enrollments" on public.enrollments for select using (auth.uid() = user_id);
create policy "users read own progress" on public.progress for select using (auth.uid() = user_id);
create policy "users write own progress" on public.progress for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "users read own orders" on public.orders for select using (auth.uid() = user_id);
create policy "users create own messages" on public.messages for insert with check (auth.uid() = user_id or user_id is null);
create policy "visitors add visits" on public.visits for insert with check (true);
create policy "visitors join newsletter" on public.newsletter for insert with check (true);

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, name) values (new.id, coalesce(new.raw_user_meta_data->>'name',''));
  return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
for each row execute procedure public.handle_new_user();
