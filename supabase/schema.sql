-- ============================================================================
-- Supabase schema for the realty site.
-- Run this in the Supabase SQL editor (Dashboard -> SQL -> New query -> Run).
-- ============================================================================

-- ---------- listings: the web-ready cache synced from Zoho ----------
create table if not exists public.listings (
  id          text primary key,
  slug        text unique not null,
  title       text not null,
  type        text not null default 'sale',     -- 'sale' | 'rent'
  price       numeric not null default 0,
  currency    text not null default 'AED',
  beds        int not null default 0,
  baths       int not null default 0,
  area_sqft   int not null default 0,
  location    text default '',
  community   text default '',
  status      text not null default 'available', -- 'available' | 'under_offer' | 'sold' | 'let'
  featured    boolean not null default false,
  description text default '',
  images      jsonb not null default '[]'::jsonb, -- array of public image URLs
  agent_name  text default '',
  agent_phone text default '',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists listings_status_idx   on public.listings (status);
create index if not exists listings_type_idx      on public.listings (type);
create index if not exists listings_featured_idx  on public.listings (featured);

-- ---------- leads: website inquiries (local backup of what goes to Zoho) ----------
create table if not exists public.leads (
  id           bigint generated always as identity primary key,
  name         text not null,
  email        text not null,
  phone        text default '',
  message      text default '',
  listing_slug text default '',
  created_at   timestamptz not null default now()
);

-- ---------- Row Level Security ----------
-- The site reads listings using the SERVICE ROLE key (server-side only), which
-- bypasses RLS, so we keep RLS ON and grant no public policies. Nothing is
-- publicly readable/writable via the anon key. Leads are write-only from server.
alter table public.listings enable row level security;
alter table public.leads    enable row level security;

-- ---------- Storage bucket for re-hosted listing photos ----------
-- Create a PUBLIC bucket named 'listing-photos' (matches SUPABASE_BUCKET).
-- Easiest in the dashboard: Storage -> New bucket -> name 'listing-photos' -> Public.
-- Or via SQL:
insert into storage.buckets (id, name, public)
values ('listing-photos', 'listing-photos', true)
on conflict (id) do nothing;
