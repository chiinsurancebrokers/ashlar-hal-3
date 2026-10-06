-- HAL leads: every proposal request and comparison request is stored here
-- BEFORE any email is sent, so a broken mail key can never lose a prospect.
-- Server-side access only (service role); RLS on, no anon/authenticated grants.

create table if not exists public.hal_leads (
  id              uuid primary key default gen_random_uuid(),
  reference       text not null unique,
  kind            text not null check (kind in ('proposal', 'comparison')),
  created_at      timestamptz not null default now(),
  email           text not null,
  name            text,
  phone           text,
  insurance_interest text,
  payload         jsonb not null default '{}'::jsonb,
  delivery_status text not null default 'pending'
                  check (delivery_status in ('pending', 'sent', 'failed')),
  delivery_error  text,
  transport       text,
  delivered_at    timestamptz
);

create index if not exists hal_leads_created_at_idx on public.hal_leads (created_at desc);
create index if not exists hal_leads_undelivered_idx on public.hal_leads (delivery_status)
  where delivery_status <> 'sent';

alter table public.hal_leads enable row level security;
revoke all on public.hal_leads from anon, authenticated;

comment on table public.hal_leads is
  'HAL proposal/comparison requests, saved before email delivery. delivery_status <> ''sent'' means the adviser email failed: follow up manually. Server-side access only.';
