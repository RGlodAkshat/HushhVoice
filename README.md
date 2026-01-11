# HushhVoice — Consent-first AI Copilot (Flask)

HushhVoice is a private AI assistant with Gmail/Calendar support, Siri/Shortcuts integration, and onboarding flows. The backend lives in `api/` and runs as a Flask app.

## Project Structure

```
/project
├── api/
│   ├── index.py              # Flask entrypoint (imports modules, runs app)
│   ├── app_context.py        # App config, OpenAI client, logging, CORS
│   ├── json_helpers.py       # jok/jerror + JSON file helpers
│   ├── auth_helpers.py       # Google token helpers
│   ├── google_helpers.py     # Google Calendar API helpers
│   ├── openai_helpers.py     # OpenAI message handling + chat wrapper
│   ├── intent_helpers.py     # Intent classification helper
│   ├── mail_helpers.py       # Gmail fetching + LLM mail QA + drafting
│   ├── calendar_helpers.py   # Calendar Q&A + planning helpers
│   ├── error_handlers.py     # Flask error handlers (404/500)
│   ├── routes_meta.py        # /health, /version
│   ├── routes_intent.py      # /intent/classify
│   ├── routes_echo.py        # /echo + /echo/stream
│   ├── routes_siri.py        # /siri/ask
│   ├── routes_mail.py        # /mailgpt/answer + /mailgpt/reply
│   ├── routes_calendar.py    # /calendar/answer + /calendar/plan
│   ├── routes_tts.py         # /tts
│   ├── routes_onboarding_agent.py  # /onboarding/agent/*
│   ├── routes_profile.py     # /profile (Supabase-backed profile)
│   └── routes_identity_enrich.py   # /identity/enrich
├── backend/                  # Supporting agent code (email helpers, etc.)
├── frontend/                 # Web UI (if used)
└── requirements.txt
```

## Backend Overview (api/)

- `index.py` is the entrypoint. It only imports modules so their routes register on the Flask `app`, then runs the server.
- `app_context.py` centralizes configuration, logging, OpenAI client setup, and Flask+CORS init so every module shares the same app instance.
- `json_helpers.py` provides consistent response shapes (`jok`, `jerror`) used by all routes.
- `auth_helpers.py` and `google_helpers.py` wrap Google OAuth token handling and Calendar API calls.
- `openai_helpers.py` contains the message normalization and OpenAI chat wrapper used by multiple endpoints.
- `intent_helpers.py`, `mail_helpers.py`, and `calendar_helpers.py` group reusable logic for intent classification, Gmail Q&A/drafting, and Calendar Q&A/planning.
- `routes_*.py` files each define a small set of related endpoints.
- `routes_onboarding_agent.py` implements the Kai onboarding agent with Supabase-backed state.
- `routes_profile.py` stores user profile data (name/phone/email) in Supabase.

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
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
PORT=5050
VERIFY_GOOGLE_TOKEN=false
DEFAULT_TZ=UTC

HUSHHVOICE_URL_SUPABASE=...
HUSHHVOICE_SERVICE_ROLE_KEY_SUPABASE=...
HUSHHVOICE_ONBOARDING_TABLE_SUPABASE=kai_onboarding_public_test
HUSHHVOICE_ONBOARDING_STATE_COLUMN=state
HUSHHVOICE_PROFILE_TABLE_SUPABASE=kai_user_profile
HUSHHVOICE_SUPABASE_TIMEOUT_SECS=5
HUSHH_ONBOARDING_CACHE_TTL=5
```

## Common Endpoints

- `GET /health`
- `POST /siri/ask`
- `POST /echo` and `POST /echo/stream`
- `POST /mailgpt/answer` and `POST /mailgpt/reply`
- `POST /calendar/answer` and `POST /calendar/plan`
- `POST /tts`
- `GET /profile`, `POST /profile`
- `GET /onboarding/agent/config`
- `POST /onboarding/agent/token`
- `POST /onboarding/agent/tool`
- `GET /onboarding/agent/state`
- `POST /onboarding/agent/reset`

If you want this README to include frontend or iOS steps, tell me what to add.
