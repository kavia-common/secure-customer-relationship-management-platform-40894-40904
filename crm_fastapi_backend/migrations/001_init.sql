-- Initial schema for CRM backend

-- Ensure tracker exists (idempotent) even if the runner didn't create it yet
create table if not exists schema_migrations (
    filename text primary key,
    applied_at timestamptz not null default now()
);

create table if not exists users (
    id bigserial primary key,
    email text not null unique,
    password_algo text not null,
    password_iterations int not null,
    password_salt text not null,
    password_hash text not null,
    role text not null default 'agent',
    created_at timestamptz not null default now()
);

create table if not exists sessions (
    token text primary key,
    user_id bigint not null references users(id) on delete cascade,
    expires_at timestamptz not null,
    revoked boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists customers (
    id bigserial primary key,
    name text not null,
    email text null,
    phone text null,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists interactions (
    id bigserial primary key,
    customer_id bigint not null references customers(id) on delete cascade,
    type text not null,
    channel text not null,
    content text not null,
    meta jsonb not null default '{}'::jsonb,
    created_by bigint null,
    created_at timestamptz not null default now()
);

create table if not exists requests (
    id bigserial primary key,
    customer_id bigint not null references customers(id) on delete restrict,
    subject text not null,
    description text not null,
    status text not null default 'open',
    priority text not null default 'normal',
    meta jsonb not null default '{}'::jsonb,
    assignee_id bigint null,
    sla_due_at timestamptz null,
    created_by bigint null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_requests_customer_id on requests(customer_id);
create index if not exists idx_requests_status on requests(status);
create index if not exists idx_requests_assignee on requests(assignee_id);

create table if not exists request_history (
    id bigserial primary key,
    request_id bigint not null references requests(id) on delete cascade,
    from_status text null,
    to_status text not null,
    note text null,
    changed_by bigint null,
    changed_at timestamptz not null default now()
);

create table if not exists workflows (
    id bigserial primary key,
    key text not null unique,
    definition jsonb not null default '{}'::jsonb,
    status text not null default 'draft',
    version int not null default 1,
    published_at timestamptz null,
    created_at timestamptz not null default now()
);

create table if not exists roles (
    id bigserial primary key,
    name text not null unique
);

create table if not exists audit_log (
    id bigserial primary key,
    user_id bigint null,
    action text not null,
    resource text not null,
    resource_id bigint null,
    details jsonb not null default '{}'::jsonb,
    ip text null,
    created_at timestamptz not null default now()
);

-- Optional helpful indexes
create index if not exists idx_audit_log_resource on audit_log(resource);
create index if not exists idx_audit_log_user on audit_log(user_id);
