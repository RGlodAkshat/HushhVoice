-- Chat core tables for streaming sessions and orchestration.

create table if not exists chat_sessions (
    session_id uuid primary key,
    user_id text not null,
    device_id text,
    started_at timestamptz default now(),
    last_seen_at timestamptz,
    realtime_health jsonb,
    fallback_count int default 0,
    app_version text
);

create table if not exists chat_turns (
    turn_id uuid primary key,
    thread_id uuid,
    user_id text not null,
    input_mode text,
    execution_mode text,
    pipeline text,
    state text,
    started_at timestamptz default now(),
    ended_at timestamptz,
    outcome text,
    error_code text,
    trace_id text,
    request_id text,
    session_id uuid
);

create index if not exists idx_chat_turns_user_id on chat_turns (user_id);
create index if not exists idx_chat_turns_thread_id on chat_turns (thread_id);
create index if not exists idx_chat_turns_state on chat_turns (state);

create table if not exists tool_runs (
    tool_run_id uuid primary key,
    turn_id uuid references chat_turns(turn_id),
    step_index int,
    tool_name text,
    status text,
    idempotency_key text unique,
    input jsonb,
    output_summary jsonb,
    started_at timestamptz default now(),
    finished_at timestamptz,
    error_code text
);

create index if not exists idx_tool_runs_turn_id on tool_runs (turn_id);

create table if not exists confirmation_requests (
    confirmation_request_id uuid primary key,
    turn_id uuid references chat_turns(turn_id),
    action_type text,
    preview jsonb,
    status text,
    created_at timestamptz default now(),
    resolved_at timestamptz,
    expires_at timestamptz
);

create index if not exists idx_confirmation_turn_id on confirmation_requests (turn_id);

create table if not exists memories (
    memory_id uuid primary key,
    user_id text not null,
    type text,
    content text,
    source text,
    confidence numeric,
    created_at timestamptz default now(),
    updated_at timestamptz,
    archived_at timestamptz
);

create index if not exists idx_memories_user_id on memories (user_id);
