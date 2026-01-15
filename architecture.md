# HushhVoice Architecture

## Scope and sources
- Backend: `HushhVoice/api/*.py` and `HushhVoice/backend/agents/*`
- iOS app: `HushhVoice_v2/HushhVoice/HushhVoice/*.swift`
- Optional web UI: `HushhVoice/frontend/*`

This document captures the current architecture from code and recent updates and defines a target architecture aligned with TOGAF viewpoints and 12-factor principles.

## Business architecture (TOGAF)
### Stakeholders
- End users: chat, voice, Gmail/Calendar assistance, onboarding
- Product and operations: reliability, privacy, consent-first behavior
- External providers: OpenAI, Google, Supabase, Apple

### Business capabilities
- Conversational assistant (chat and voice)
- Siri and Shortcuts integration
- Gmail reading, summarization, and reply drafting/sending
- Google Calendar Q and A and scheduling
- Investor onboarding flow (Kai agent)
- Kai Notes (lightweight, per-answer summaries)
- Summary review and edit
- User profile capture and lightweight identity enrichment
- Account deletion and local state reset

### Policies and constraints
- Consent-first, privacy-first messaging
- Do not request highly sensitive identifiers in onboarding flow
- External access tokens are provided by the client per request

## Application architecture (TOGAF)
### Logical components
- iOS app (SwiftUI): chat UI, Siri Shortcuts, TTS playback, Google OAuth PKCE, Apple Sign In to Supabase, onboarding voice with OpenAI Realtime (WebRTC), onboarding resume from Supabase, premium onboarding UI (intro steps, Meet Kai, Summary)
- Backend API (Flask): REST endpoints for chat, mail, calendar, onboarding, profile, identity enrichment, TTS
- Agent modules: Gmail fetcher, reply drafting helper, (placeholder) health assistant
- Optional web UI: basic web client for chat and testing
- Third-party services: OpenAI (chat, TTS, realtime), Google APIs (Gmail/Calendar), Supabase (profile and onboarding state), Apple Sign In

### Core backend routes (current)
- `GET /health`, `GET /version`
- `POST /echo`, `POST /echo/stream`
- `POST /intent/classify`
- `POST /siri/ask`
- `POST /mailgpt/answer`, `POST /mailgpt/reply`
- `POST /calendar/answer`, `POST /calendar/plan`
- `POST /tts`
- `GET /profile`, `POST /profile`
- `POST /account/delete`
- `GET /onboarding/agent/config`, `POST /onboarding/agent/token`, `POST /onboarding/agent/tool`, `POST /onboarding/agent/sync`, `GET /onboarding/agent/state`, `POST /onboarding/agent/reset`
- `POST /identity/enrich`

### iOS onboarding flow (current)
- Stages: `loading` → `profile` → `intro1` → `intro2` → `meetKai` → `voice` → `summary` → `actions`
- On app open, iOS performs a single startup check:
  - `GET /profile?user_id=...`
  - `GET /onboarding/agent/config?user_id=...`
- Routing rules:
  - Profile incomplete → `profile`
  - Profile complete + onboarding incomplete → `intro1/intro2` (if not done) or `voice` (resume)
  - Profile complete + onboarding complete → exit onboarding (main app)
- Voice resume uses `next_question_text` and `missing_keys` from config and preserves local state while reconnecting WebRTC.
- “Go to HushhTech” routes to Summary first if onboarding complete; otherwise resumes onboarding.

### iOS UI highlights (current)
- Auth gate: logo orb with breathing animation, primary Google sign-in, Apple secondary, guest tertiary; trust copy without bank language
- Intro steps (1–4): premium glass cards, progress dots, logo orb on Steps 2 and 4
- Voice onboarding: Kai orb + waveform driven by mic level, muted state preserved, notes card capped + scrollable
- Kai Notes: newest entry animates only once, auto-scroll pinned during animation, notes stored per-answer
- Summary: hero grid with edit icon, highlight pills, accordion sections with confidence pills, sticky CTA + “Open HushhTech”

## Data architecture (TOGAF)
### Data domains
- User identity: Apple Sign In user id and Supabase user id
- OAuth tokens: Google access and refresh tokens (stored on device)
- Conversation history: stored on device (UserDefaults)
- Onboarding state: local persistent cache (UserDefaults JSON per user id) with Supabase as source of truth on app open; backend falls back to `/tmp` if Supabase is not configured
- Profile data: Supabase table storing name, phone, email
- Supabase tables: `kai_onboarding_state`, `kai_user_profile`
- Kai Notes: stored locally as an ordered list and optionally sourced from Supabase `notes_tail` via config
- Email and calendar data: transient, fetched on demand

### Data flows and storage
- iOS app stores Google tokens in App Group UserDefaults for reuse across app and Shortcuts
- Backend fetches Gmail and Calendar data using short-lived access tokens passed by the client
- Onboarding state is cached in memory, persisted locally in UserDefaults, and overwritten on app open by Supabase config when available
- Account deletion triggers `/account/delete` to remove Supabase rows and clears local onboarding/profile state on device
- No server-side long-term chat memory is currently persisted

### Local persistence and sync (iOS)
- `KaiLocalState` is encoded to JSON and stored in UserDefaults with key prefix `hushh_kai_onboarding_state_v1_{user_id}`
- Sync pending is tracked via a UserDefaults flag `hushh_kai_onboarding_sync_pending_{user_id}`
- On config fetch, iOS overwrites local discovery, counts, next question, and optionally notes from `notes_tail`
- Supabase sync is triggered after Summary is shown; UI does not block on sync

## Technology architecture (TOGAF)
### Platforms and frameworks
- Backend: Python, Flask, OpenAI SDK, requests, googleapiclient, Supabase REST
- iOS: SwiftUI, AppIntents, AVFoundation (AVAudioEngine mic level monitor + waveform), ASWebAuthenticationSession, Supabase SDK, LiveKitWebRTC, Orb
- Hosting: local run, gunicorn; ngrok for mobile testing

### Security and trust boundaries
- App auth in `/siri/ask` is a placeholder JWT check (TODO in code)
- Google access tokens are supplied by client per request
- OpenAI Realtime uses ephemeral client_secret generated by backend
- Supabase service role key used server-side for onboarding/profile writes

## C4 architecture diagrams (mermaid)

### C1: System context
```mermaid
C4Context
title HushhVoice System Context

Person(user, "User", "Mobile or web user")

System_Boundary(hv, "HushhVoice") {
  System(ios, "HushhVoice iOS App", "SwiftUI app with chat, Siri, onboarding voice")
  System(web, "HushhVoice Web UI", "Optional web client")
  System(api, "HushhVoice API", "Flask backend with REST endpoints")
}

System_Ext(openai, "OpenAI API", "Chat, TTS, Realtime")
System_Ext(google, "Google APIs", "Gmail and Calendar")
System_Ext(supabase, "Supabase", "Auth and data store")
System_Ext(apple, "Apple Sign In", "Identity provider")

Rel(user, ios, "Uses")
Rel(user, web, "Uses")
Rel(ios, api, "HTTPS JSON endpoints")
Rel(web, api, "HTTPS JSON endpoints")
Rel(api, openai, "Chat and TTS")
Rel(ios, openai, "Realtime WebRTC using ephemeral client_secret")
Rel(api, google, "Gmail and Calendar APIs")
Rel(api, supabase, "Profile and onboarding state")
Rel(ios, supabase, "Apple auth via Supabase SDK")
Rel(apple, supabase, "OIDC provider")
```

### C2: Container diagram
```mermaid
C4Container
title HushhVoice Container Diagram

Person(user, "User")

System_Boundary(hv, "HushhVoice") {
  Container(ios, "iOS App", "SwiftUI", "Chat UI, Siri intents, onboarding voice, OAuth, TTS playback, local onboarding cache")
  Container(web, "Web UI", "HTML/JS", "Optional web client for chat/testing")
  Container(api, "Backend API", "Python Flask", "REST endpoints and orchestration")
  ContainerDb(state, "Onboarding State", "Supabase or /tmp JSON", "Kai onboarding state")
  ContainerDb(profile, "Profile Store", "Supabase", "User profile data")
  ContainerDb(local, "Local Onboarding Cache", "UserDefaults", "KaiLocalState + Kai Notes")
}

System_Ext(openai, "OpenAI", "Chat, TTS, Realtime")
System_Ext(google, "Google APIs", "Gmail and Calendar")
System_Ext(apple, "Apple Sign In", "Identity provider")

Rel(user, ios, "Uses")
Rel(user, web, "Uses")
Rel(ios, api, "HTTPS JSON")
Rel(web, api, "HTTPS JSON")
Rel(ios, local, "Read/write state")
Rel(api, state, "Read/write")
Rel(api, profile, "Read/write")
Rel(api, openai, "Chat/TTS")
Rel(ios, openai, "Realtime WebRTC")
Rel(api, google, "Gmail/Calendar")
Rel(ios, apple, "Sign-in")
```

### C3: Component diagram (backend)
```mermaid
C4Component
title HushhVoice API Components (Flask)

Container_Boundary(api, "HushhVoice API") {
  Component(routes_meta, "routes_meta", "Flask routes", "/health, /version")
  Component(routes_echo, "routes_echo", "Flask routes", "/echo, /echo/stream")
  Component(routes_intent, "routes_intent", "Flask routes", "/intent/classify")
  Component(routes_siri, "routes_siri", "Flask routes", "/siri/ask")
  Component(routes_mail, "routes_mail", "Flask routes", "/mailgpt/*")
  Component(routes_calendar, "routes_calendar", "Flask routes", "/calendar/*")
  Component(routes_tts, "routes_tts", "Flask routes", "/tts")
  Component(routes_onboarding, "routes_onboarding_agent", "Flask routes", "/onboarding/agent/*")
  Component(routes_profile, "routes_profile", "Flask routes", "/profile")
  Component(routes_account, "routes_account", "Flask routes", "/account/delete")
  Component(routes_identity, "routes_identity_enrich", "Flask routes", "/identity/enrich")

  Component(auth_helpers, "auth_helpers", "Helper", "Token extraction/verification")
  Component(openai_helpers, "openai_helpers", "Helper", "Chat wrapper and system prompt")
  Component(mail_helpers, "mail_helpers", "Helper", "Mail Q and A and draft")
  Component(calendar_helpers, "calendar_helpers", "Helper", "Calendar Q and A and plan")
  Component(intent_helpers, "intent_helpers", "Helper", "Intent classification")
  Component(google_helpers, "google_helpers", "Helper", "Calendar REST calls")

  Component(gmail_fetcher, "gmail_fetcher", "Agent module", "Gmail fetch/send")
  Component(reply_helper, "reply_helper", "Agent module", "Draft reply with OpenAI")
  Component(onboarding_state, "Onboarding state manager", "State logic", "Cache + Supabase + disk")
}

Container_Ext(openai, "OpenAI API", "Chat, TTS, Realtime")
Container_Ext(google, "Google APIs", "Gmail and Calendar")
ContainerDb(supabase, "Supabase", "Profile + onboarding state")

Rel(routes_siri, intent_helpers, "Classify intent")
Rel(routes_siri, mail_helpers, "Email flows")
Rel(routes_siri, calendar_helpers, "Calendar flows")
Rel(routes_siri, openai_helpers, "General chat")
Rel(routes_mail, gmail_fetcher, "Fetch/send Gmail")
Rel(mail_helpers, reply_helper, "Draft replies")
Rel(routes_calendar, google_helpers, "Calendar REST")
Rel(routes_onboarding, onboarding_state, "Load/save state")

Rel(routes_tts, openai, "TTS")
Rel(openai_helpers, openai, "Chat")
Rel(google_helpers, google, "Calendar")
Rel(gmail_fetcher, google, "Gmail")
Rel(onboarding_state, supabase, "State store")
Rel(routes_profile, supabase, "Profile store")
Rel(routes_identity, openai, "Inference")
```

## C4 dynamic workflows (mermaid)

### Siri ask flow
```mermaid
sequenceDiagram
participant User
participant iOS as iOS App
participant API as HushhVoice API
participant OpenAI as OpenAI API
participant Google as Google APIs

User->>iOS: Speak or type question
iOS->>API: POST /siri/ask (prompt, app_jwt, google_access_token)
API->>API: classify_intent_text()
alt General chat
  API->>OpenAI: Chat completion
  OpenAI-->>API: Answer
else Email intent
  API->>Google: Gmail fetch/send
  Google-->>API: Email data or send result
  API->>OpenAI: Summarize or draft
  OpenAI-->>API: Response
else Calendar intent
  API->>Google: Calendar list/insert
  Google-->>API: Events or created event
  API->>OpenAI: Summarize or parse
  OpenAI-->>API: Response
end
API-->>iOS: JSON {speech, display}
```

### Onboarding voice flow (Kai)
```mermaid
sequenceDiagram
participant User
participant iOS as iOS App
participant API as HushhVoice API
participant OpenAI as OpenAI Realtime
participant Supabase

iOS->>API: GET /profile
API->>Supabase: Load profile
API-->>iOS: profile (exists + fields)

iOS->>API: GET /onboarding/agent/config
API->>Supabase: Load state (if configured)
API-->>iOS: instructions, tools, kickoff, state_compact, missing_keys, next_question_text

iOS->>API: POST /onboarding/agent/token
API->>OpenAI: Create realtime session
API-->>iOS: client_secret

iOS->>OpenAI: WebRTC connect (audio + data channel)
OpenAI-->>iOS: Tool call (memory_set)
iOS->>API: POST /onboarding/agent/tool
API->>Supabase: Save state (or /tmp fallback)
API-->>iOS: tool output
iOS->>OpenAI: function_call_output
```

Notes:
- iOS updates local discovery, next_question_text, completed counts, and notes from tool output.
- Supabase sync is deferred until summary is shown.

### Mail and calendar (web or app)
```mermaid
sequenceDiagram
participant Client
participant API as HushhVoice API
participant OpenAI as OpenAI API
participant Gmail as Gmail API
participant Cal as Calendar API

Client->>API: POST /mailgpt/answer or /calendar/plan
alt Mail
  API->>Gmail: Fetch inbox
  Gmail-->>API: Email metadata
  API->>OpenAI: Summarize or draft
  OpenAI-->>API: Answer or draft
else Calendar
  API->>Cal: List or insert events
  Cal-->>API: Events or created event
  API->>OpenAI: Summarize or parse
  OpenAI-->>API: Answer or event JSON
end
API-->>Client: JSON response
```

### TTS flow
```mermaid
sequenceDiagram
participant iOS as iOS App
participant API as HushhVoice API
participant OpenAI as OpenAI API

iOS->>API: POST /tts
API->>OpenAI: audio.speech.create
OpenAI-->>API: Audio bytes (mp3)
API-->>iOS: audio/mpeg
```

## 12-factor alignment (current vs target)
| Factor | Current state | Target state |
| --- | --- | --- |
| 1. Codebase | Single repo with backend and iOS | Keep mono-repo or split with clear ownership |
| 2. Dependencies | `requirements.txt` and Swift packages | Pin versions and use lockfiles where possible |
| 3. Config | `.env` plus environment variables | Move secrets out of code, use secret manager |
| 4. Backing services | OpenAI, Google, Supabase are attached | Keep them replaceable via config |
| 5. Build/release/run | Manual local run, gunicorn | CI/CD with build and release stages |
| 6. Processes | Some state in memory and `/tmp` | Make services stateless; persist in DB/Redis |
| 7. Port binding | `PORT` env supported | Keep |
| 8. Concurrency | Scale via gunicorn or serverless | Document process model and autoscale |
| 9. Disposability | No explicit shutdown handling | Add timeouts and graceful shutdown hooks |
| 10. Dev/prod parity | ngrok for dev | Use staging with same services |
| 11. Logs | Python logging to stdout | Structured logs + centralized aggregation |
| 12. Admin processes | None defined | Add one-off jobs (migrations, backfills) |

## Target architecture (ideal)
### Target principles
- Consent-first and privacy-first by default
- Zero trust between client and backend
- Stateless API services with durable data stores
- Event-driven for long-running tasks
- Observability as a first-class concern

### Target container view (proposed)
```mermaid
flowchart LR
subgraph Clients
  iOS[iOS App]
  Web[Web UI]
  Siri[Siri Shortcuts]
end

subgraph Edge
  Gateway[API Gateway]
  Auth[Auth and Consent]
end

subgraph Core
  Orchestrator[LLM Orchestrator]
  MailSvc[Mail Service]
  CalendarSvc[Calendar Service]
  OnboardingSvc[Onboarding Service]
  ProfileSvc[Profile Service]
  TtsSvc[TTS Service]
  Worker[Async Worker]
  Cache[Redis Cache]
  DB[(Postgres or Supabase)]
  Vector[(Vector Store)]
  Obj[(Object Storage)]
end

OpenAI[OpenAI API]
Google[Google APIs]
Apple[Apple Sign In]
Obs[Logs, metrics, traces]

iOS --> Gateway
Web --> Gateway
Siri --> Gateway
Gateway --> Auth
Auth --> Orchestrator
Orchestrator --> OpenAI
MailSvc --> Google
CalendarSvc --> Google
OnboardingSvc --> OpenAI
OnboardingSvc --> DB
ProfileSvc --> DB
Orchestrator --> Cache
Worker --> DB
Worker --> Obj
Gateway --> Obs
```

### Key changes from baseline
- Implement real app auth (JWT validation, session management, rate limiting)
- Move all onboarding and profile state to a durable database and add caching
- Add a token broker or vault for Google access and refresh tokens server-side
- Separate long-running AI tasks into background workers
- Add central observability, audit logs, and consent tracking
- Provide a stable environment separation for dev/staging/prod

## Gaps and risks observed in code
- App auth in `/siri/ask` is a placeholder and should be enforced
- Onboarding state falls back to `/tmp` storage if Supabase is not configured
- Health assistant code is present but not wired into the API
- Onboarding resume depends on Supabase config availability; when offline, local cache is used and may drift from server state
- Realtime voice relies on short-lived client_secret tokens; token refresh failure results in reconnect and potential user interruption
