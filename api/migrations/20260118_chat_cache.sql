-- Chat cache tables for Gmail/Calendar + cache state

create table if not exists gmail_message_index (
    user_id text not null,
    message_id text not null,
    thread_id text,
    internal_date timestamptz,
    from_email text,
    from_name text,
    subject text,
    date_label text,
    snippet text,
    labels jsonb,
    raw jsonb,
    updated_at timestamptz default now(),
    primary key (user_id, message_id)
);

create index if not exists idx_gmail_message_index_user_date
    on gmail_message_index (user_id, internal_date desc);
create index if not exists idx_gmail_message_index_from
    on gmail_message_index (user_id, from_email);

create table if not exists calendar_event_cache (
    user_id text not null,
    event_id text not null,
    summary text,
    start_time timestamptz,
    end_time timestamptz,
    location text,
    attendees jsonb,
    html_link text,
    raw jsonb,
    updated_at timestamptz default now(),
    primary key (user_id, event_id)
);

create index if not exists idx_calendar_event_cache_user_start
    on calendar_event_cache (user_id, start_time);

create table if not exists cache_state (
    user_id text primary key,
    gmail_last_sync_ts timestamptz,
    gmail_history_id text,
    calendar_sync_token text,
    calendar_last_sync_ts timestamptz,
    updated_at timestamptz default now()
);

-- Existing turn/tool/confirmation tables should already exist; ensure idempotency index.
create unique index if not exists idx_tool_runs_idempotency
    on tool_runs (idempotency_key);
