# HushhVoice — Consent-first AI Copilot (Flask + iOS)

HushhVoice is a private, consent-first AI assistant with Gmail/Calendar tools, realtime voice, and onboarding flows. The backend lives in `api/` (Flask) and the iOS app lives in `HushhVoice_v2/`.

This README reflects the current codebase: realtime chat uses OpenAI Realtime (WebRTC) as the voice shell, with server-side tool routing, confirmation gating, and read-through caches for Gmail/Calendar.

## Project Structure

```
/ProjectRoot
├── api/
│   ├── index.py              # Flask entrypoint (runs app)
│   ├── app.py                # create_app() + blueprint wiring
│   ├── config.py             # Config + env loading + logging
│   ├── routes/               # Flask blueprints per route group
│   │   ├── chat_agent.py      # Realtime config/token/tools/prefetch endpoints
│   │   ├── chat_stream.py     # WS gateway for canonical stream (if used)
│   │   └── ...
│   ├── services/             # Business logic (chat, cache, tools, onboarding)
│   │   ├── chat_realtime_service.py
│   │   ├── cache_sync_service.py
│   │   ├── tool_router_service.py
│   │   ├── orchestrator_service.py
│   │   └── turn_coordinator.py
│   ├── storage/              # Supabase persistence + cache stores
│   │   ├── gmail_cache_store.py
│   │   ├── calendar_cache_store.py
│   │   ├── cache_state_store.py
│   │   ├── turn_store.py
│   │   ├── tool_run_store.py
│   │   └── confirmation_store.py
│   ├── clients/              # OpenAI/Google client wrappers
│   ├── utils/                # shared helpers + debug events
│   └── schemas/              # soft typing for request/response shapes
├── backend/                  # Supporting agent code (email helpers, etc.)
├── frontend/                 # Optional static web UI
├── HushhVoice_v2/            # iOS app (SwiftUI)
│   └── HushhVoice/HushhVoice # App source
├── architecture.md
└── requirements.txt
```

## Backend Overview (api/)

- `routes/chat_agent.py` exposes realtime chat endpoints:
  - `GET /chat/agent/config` (tools + instructions + turn detection)
  - `POST /chat/agent/token` (OpenAI Realtime client_secret)
  - `POST /chat/agent/tool` (server-side tool routing)
  - `POST /chat/agent/confirm` (confirmation gating)
  - `POST /chat/agent/prefetch` (speculative cache warmup)
- `services/chat_realtime_service.py` enforces tool usage, confirmation gating, idempotency, and prefetch behavior.
- `services/tool_router_service.py` runs Gmail/Calendar/Memory tools and performs read-through cache checks.
- `services/cache_sync_service.py` keeps Gmail/Calendar caches fresh using incremental sync (Gmail historyId, Calendar sync token).
- `services/turn_coordinator.py` + `storage/turn_store.py` provide turn lifecycle tracking.
- `storage/*_cache_store.py` provide Supabase-backed cache tables for low-latency reads.

## iOS App Overview (HushhVoice_v2/)

- `ChatView` is the single chat surface.
- `ChatRealtimeSession` opens a WebRTC session to OpenAI Realtime for voice input/output and live transcripts.
- Tools run via backend endpoints (no client-side Gmail/Calendar calls).
- If realtime is unhealthy, the UI falls back to on-device STT + backend `/siri/ask` + TTS.
- Live transcript is rendered in a draft bubble; assistant text streams in sync with audio.

## Realtime Chat Flow (high level)

1. iOS calls `/chat/agent/config` and `/chat/agent/token`.
2. iOS opens WebRTC to OpenAI Realtime with the ephemeral token.
3. User speech -> OpenAI transcript deltas -> chat UI draft bubble.
4. Realtime model emits tool calls -> iOS forwards to `/chat/agent/tool`.
5. Tool router uses caches (Gmail/Calendar/Memory) and returns outputs.
6. Writes (send email/create event) require confirmation via `/chat/agent/confirm`.

## Environment Variables (backend)

```
APP_NAME=HushhVoice API
APP_VERSION=0.5.0
PORT=5050
DEBUG=true
DEBUG_CONSOLE_ENABLED=true
DEBUG_EVENTS_MAX=1000

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_EMBED_MODEL=text-embedding-3-small
OPENAI_SUMMARY_MODEL=gpt-4.1-nano
OPENAI_REALTIME_MODEL=gpt-4o-realtime-preview
FLASK_SECRET=change-me
VERIFY_GOOGLE_TOKEN=false

HUSHHVOICE_URL_SUPABASE=...
HUSHHVOICE_SERVICE_ROLE_KEY_SUPABASE=...
HUSHHVOICE_SUPABASE_TIMEOUT_SECS=5

# Core tables
HUSHHVOICE_PROFILE_TABLE_SUPABASE=kai_user_profile
HUSHHVOICE_ONBOARDING_TABLE_SUPABASE=kai_onboarding_state
HUSHHVOICE_ONBOARDING_STATE_COLUMN=state
HUSHHVOICE_TURNS_TABLE_SUPABASE=chat_turns
HUSHHVOICE_TOOL_RUNS_TABLE_SUPABASE=tool_runs
HUSHHVOICE_CONFIRM_TABLE_SUPABASE=confirmation_requests
HUSHHVOICE_SESSIONS_TABLE_SUPABASE=sessions

# Memory tables
HUSHHVOICE_MEMORY_TABLE_SUPABASE=memories
HUSHHVOICE_MEMORY_COLUMN_SUPABASE=content
HUSHHVOICE_MEMORIES_TABLE_SUPABASE=memories

# Cache tables
HUSHHVOICE_GMAIL_CACHE_TABLE_SUPABASE=gmail_message_index
HUSHHVOICE_CAL_CACHE_TABLE_SUPABASE=calendar_event_cache
HUSHHVOICE_CACHE_STATE_TABLE_SUPABASE=cache_state
```

## Common Endpoints

- `GET /health`
- `POST /siri/ask` (classic STT->LLM->TTS fallback)
- `POST /tts`
- `GET /profile`, `POST /profile`
- `POST /account/delete`
- `GET /onboarding/agent/config`
- `POST /onboarding/agent/token`
- `POST /onboarding/agent/tool`
- `POST /onboarding/agent/sync`
- `POST /onboarding/agent/reset`
- `GET /chat/agent/config`
- `POST /chat/agent/token`
- `POST /chat/agent/tool`
- `POST /chat/agent/confirm`
- `POST /chat/agent/prefetch`
- `WS /chat/stream` (canonical stream; optional)

## Supabase Tables (current)

- `kai_user_profile`
- `kai_onboarding_state`
- `sessions`
- `chat_turns`
- `tool_runs`
- `confirmation_requests`
- `memories`
- `gmail_message_index`
- `calendar_event_cache`
- `cache_state`
- `chat_threads` (optional)
- `chat_messages` (optional)
- `oauth_tokens` (optional)

## How To Run The Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python api/index.py
```

Optional ngrok:

```bash
ngrok http 5050
```

## Tests

```bash
pytest
```

## Notes

- Realtime voice uses WebRTC directly between iOS and OpenAI.
- Tool calls and confirmations always go through the backend.
- Gmail/Calendar reads are served from cache when possible; refresh happens asynchronously.
