# HushhVoice — Consent-first AI Copilot (Flask)

HushhVoice is a private AI assistant with Gmail/Calendar support, Siri/Shortcuts integration, and onboarding flows. The backend lives in `api/` and runs as a Flask app; the iOS app is in `HushhVoice_v2/`.

## Project Structure

```
/project
├── api/
│   ├── index.py              # Flask entrypoint (runs app)
│   ├── app.py                # create_app() + blueprint wiring
│   ├── config.py             # Config + env loading + logging
│   ├── routes/               # Flask blueprints per route group
│   ├── services/             # Business logic (mail/calendar/onboarding/etc.)
│   ├── storage/              # Supabase + onboarding state persistence
│   ├── clients/              # OpenAI/Google client wrappers
│   ├── utils/                # shared helpers (jok/jerror, auth)
│   └── schemas/              # soft typing for request/response shapes
├── backend/                  # Supporting agent code (email helpers, etc.)
├── frontend/                 # Web UI (if used)
├── HushhVoice_v2/            # iOS app (SwiftUI)
│   └── HushhVoice/HushhVoice # App source
├── architecture.md
└── requirements.txt
```

## Backend Overview (api/)

- `index.py` is the entrypoint. It runs the Flask app exposed by `app.py`.
- `app.py` defines the app factory and registers all route blueprints.
- `config.py` centralizes configuration, logging, env loading, and path setup.
- `utils/json_helpers.py` provides consistent response shapes (`jok`, `jerror`) used by all routes.
- `utils/auth_helpers.py` wraps Google OAuth token handling.
- `clients/openai_client.py` and `clients/google_client.py` wrap OpenAI and Google calls.
- `services/*` contain route-independent business logic (onboarding, mail, calendar, tool router, memory, etc.).
- `services/tool_router_service.py` powers `/siri/ask` with OpenAI tool calling (Gmail, Calendar, memory).
- `services/chat_gateway.py` powers `/chat/stream` for streaming chat events (text deltas, tool progress, confirmations).
- `services/memory_service.py` and `storage/memory_store.py` manage embedding-backed memory storage.
- `storage/*` isolates disk/Supabase persistence for onboarding, profiles, and memory.
- `routes/debug.py` exposes an in-memory debug console (when enabled).
- `utils/debug_events.py` stores request/response debug events.
- `routes/*` define the endpoint handlers, grouped by domain.

## iOS App Overview (HushhVoice_v2/)

- Entry point: `HushhVoiceApp.swift` launches `ChatView` and restores Apple Supabase sessions.
- Network: `Services/HushhAPI.swift` defines the backend base URL, app JWT, and `/siri/ask`, `/tts`, `/account/delete` calls (update `base` for your backend).
- Auth: `GoogleSignInManager` (OAuth PKCE + App Group token storage) and `AppleSupabaseAuth` (Sign in with Apple -> Supabase).
- Onboarding: `OnboardingCoordinator` + `KaiVoiceViewModel` (OpenAI Realtime WebRTC) with local caching and `/onboarding/agent/sync` to Supabase.

## How To Run The Backend

### 1) Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .\.venv\Scripts\activate  # Windows
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Start the Flask backend

```bash
python api/index.py
```

The server will listen on port `5050` by default (or whatever `PORT` is set to).

If you prefer gunicorn:

```bash
gunicorn api.index:app --bind 0.0.0.0:5050
```

### 4) Expose with ngrok (optional for mobile testing)

```bash
ngrok http 5050
```

Use the HTTPS URL printed by ngrok (example: `https://xxxx.ngrok-free.app`) in your iOS app base URL.

## Environment Variables (example)

Create a `.env` at the project root (or set in your shell):

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
DEFAULT_TZ=UTC

HUSHHVOICE_URL_SUPABASE=...
HUSHHVOICE_SERVICE_ROLE_KEY_SUPABASE=...
HUSHHVOICE_ONBOARDING_TABLE_SUPABASE=kai_onboarding_state
HUSHHVOICE_ONBOARDING_STATE_COLUMN=state
HUSHHVOICE_PROFILE_TABLE_SUPABASE=kai_user_profile
HUSHHVOICE_SUPABASE_TIMEOUT_SECS=5
HUSHH_ONBOARDING_CACHE_TTL=5
HUSHH_ONBOARDING_STATE_DIR=/tmp/hushh_onboarding_state
HUSHH_MEMORY_STORE_PATH=/tmp/hushh_memory_store.json
HUSHHVOICE_MEMORY_TABLE_SUPABASE=hushh_memory_store
HUSHHVOICE_MEMORY_COLUMN_SUPABASE=memory
HUSHHVOICE_TURNS_TABLE_SUPABASE=chat_turns
HUSHHVOICE_TOOL_RUNS_TABLE_SUPABASE=tool_runs
HUSHHVOICE_CONFIRMATIONS_TABLE_SUPABASE=confirmation_requests
HUSHHVOICE_SESSIONS_TABLE_SUPABASE=chat_sessions
```

## Common Endpoints

- `GET /health`
- `POST /siri/ask`
- `POST /echo` and `POST /echo/stream`
- `WS /chat/stream` (canonical streaming chat events)
- `POST /intent/classify`
- `POST /mailgpt/answer` and `POST /mailgpt/reply`
- `POST /calendar/answer` and `POST /calendar/plan`
- `POST /tts`
- `GET /profile`, `POST /profile`
- `POST /identity/enrich`
- `GET /onboarding/agent/config`
- `POST /onboarding/agent/token`
- `POST /onboarding/agent/tool`
- `GET /onboarding/agent/state`
- `POST /onboarding/agent/sync`
- `POST /onboarding/agent/reset`
- `GET /debug`, `GET /debug/ui`, `GET /debug/events`, `POST /debug/clear`

Note: `/siri/ask` expects `tokens.app_jwt` and accepts an optional `tokens.google_access_token`.

## Debug Console

Set `DEBUG_CONSOLE_ENABLED=true` and open `/debug/ui` to view in-memory request and tool events.

## Tests

From the `api/` folder:

```bash
pytest
```

## Chat Streaming Notes

- The chat gateway emits canonical events: `assistant_text.delta`, `tool_call.progress`, `confirmation.request`, `turn.start/end`.
- Audio streaming events (`assistant_audio.*`) are stubbed for now and can be wired once streaming TTS is available.
