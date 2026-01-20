# HushhVoice Architecture (Current)

This document reflects the current codebase in `HushhVoice/` (backend) and `HushhVoice_v2/` (iOS).

## Scope and sources
- Backend: `api/*.py`, `backend/agents/*`
- iOS: `HushhVoice_v2/HushhVoice/HushhVoice/*.swift`
- Optional web UI: `frontend/*`

## System summary
- Single chat surface in iOS with realtime voice + streaming text.
- OpenAI Realtime (WebRTC) is the always-on voice shell when healthy.
- Backend remains the source of truth for tools, safety, confirmation gating, and caching.
- Gmail/Calendar reads are served from Supabase caches with incremental sync.
- Fallback path: on-device STT -> `/siri/ask` -> TTS (used only when realtime is unhealthy).

## Runtime flows

### 1) Realtime voice turn (primary path)
1. iOS calls `GET /chat/agent/config` for instructions + tools.
2. iOS calls `POST /chat/agent/token` for an ephemeral OpenAI Realtime token.
3. iOS opens WebRTC to OpenAI Realtime and sends `session.update`.
4. User speaks -> input transcript deltas -> UI draft bubble updates live.
5. Realtime model outputs assistant audio + transcript deltas -> UI streams text in sync.
6. If tools are needed, iOS forwards tool calls to `/chat/agent/tool`.
7. Backend executes read-through tools or asks for confirmation on writes.
8. On confirmation, iOS calls `/chat/agent/confirm`, tool executes, response continues.

### 2) Tool execution with cache
- Tool router checks Supabase caches first (`gmail_message_index`, `calendar_event_cache`).
- If cache is fresh, returns immediately and refreshes asynchronously.
- If cache is stale, triggers incremental sync using Gmail historyId or Calendar sync token.

### 3) Fallback STT path (only when realtime is unhealthy)
- iOS uses Apple Speech to capture user transcript.
- Text is sent to `/siri/ask` with Google access token if available.
- Backend runs tool router (Gmail/Calendar/Memory) and returns text.
- iOS speaks the reply via TTS.

## Application architecture

### iOS app (SwiftUI)
- `ChatView`: single chat surface, voice-first UI, streaming bubbles.
- `ChatRealtimeSession`: OpenAI Realtime WebRTC client + tool call forwarding.
- `AudioCaptureManager`: fallback STT input capture.
- `SpeechManager`: fallback TTS playback and streaming audio handling.
- `ChatStore`: local chat history, streaming state, confirmation UI.

### Backend (Flask)
- `routes/chat_agent.py`: config/token/tool/confirm/prefetch endpoints for realtime chat.
- `routes/chat_stream.py`: optional WS gateway for canonical events.
- `services/chat_realtime_service.py`: tool calling + confirmation gating + idempotency.
- `services/tool_router_service.py`: Gmail/Calendar/Memory tools with cache reads.
- `services/cache_sync_service.py`: incremental Gmail/Calendar cache updates.
- `services/orchestrator_service.py`: plan execution + parallel read-only tools.
- `services/turn_coordinator.py`: turn lifecycle tracking.
- `storage/*_store.py`: Supabase persistence (turns, tool_runs, confirmations, caches).

## Data architecture

### Supabase tables
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

### Cache strategy
- Gmail index is stored in `gmail_message_index` and refreshed incrementally using Gmail historyId.
- Calendar events are stored in `calendar_event_cache` and refreshed using sync tokens.
- `cache_state` stores `gmail_history_id`, `gmail_last_sync_ts`, `calendar_sync_token`, `calendar_last_sync_ts`.

## Security and trust boundaries
- OpenAI Realtime token is minted server-side and sent to iOS.
- Gmail/Calendar access tokens are passed from iOS to backend per request.
- All write actions require explicit confirmation.
- Supabase writes use the service role key on the backend.

## Observability
- `utils/debug_events.py` stores in-memory debug events.
- `utils/observability.py` logs turn lifecycle and cache events.

## C4 diagrams (mermaid)

### C1: System context
```mermaid
C4Context
title HushhVoice System Context

Person(user, "User", "Voice-first chat user")

System_Boundary(hv, "HushhVoice") {
  System(ios, "iOS App", "SwiftUI chat + realtime voice")
  System(api, "Backend API", "Flask tools + cache + confirmations")
  System(web, "Web UI", "Optional classic chat client")
}

System_Ext(openai, "OpenAI", "Realtime S2S + text models")
System_Ext(google, "Google APIs", "Gmail + Calendar")
System_Ext(supabase, "Supabase", "Profiles, turns, caches")

Rel(user, ios, "Uses")
Rel(user, web, "Uses")
Rel(ios, api, "HTTPS JSON (chat_agent, tools, confirmations)")
Rel(web, api, "HTTPS JSON (legacy endpoints)")
Rel(ios, openai, "WebRTC Realtime voice")
Rel(api, openai, "Text models, embeddings")
Rel(api, google, "Gmail/Calendar APIs")
Rel(api, supabase, "Read/write data")
```

### C2: Container diagram
```mermaid
C4Container
title HushhVoice Containers

Person(user, "User")

System_Boundary(hv, "HushhVoice") {
  Container(ios, "iOS App", "SwiftUI", "Chat UI, realtime WebRTC, fallback STT")
  Container(api, "Backend API", "Flask", "Tool routing, confirmations, caches")
  Container(worker, "Cache Sync Worker", "Python", "Incremental Gmail/Calendar sync")
  ContainerDb(store, "Supabase", "Postgres", "Profiles, turns, caches, memory")
  Container(web, "Web UI", "HTML/JS", "Optional classic chat UI")
}

System_Ext(openai, "OpenAI", "Realtime S2S + text models")
System_Ext(google, "Google APIs", "Gmail + Calendar")

Rel(user, ios, "Uses")
Rel(user, web, "Uses")
Rel(ios, api, "chat_agent endpoints")
Rel(ios, openai, "WebRTC Realtime")
Rel(api, openai, "Text + embeddings")
Rel(api, google, "Gmail/Calendar")
Rel(api, store, "Read/write")
Rel(worker, store, "Update caches")
Rel(worker, google, "Incremental sync")
Rel(web, api, "Legacy REST endpoints")
```

### C3: Backend components
```mermaid
C4Component
title HushhVoice Backend Components

Container_Boundary(api, "Backend API") {
  Component(routes_chat_agent, "routes/chat_agent.py", "Flask", "Realtime config/token/tools/prefetch")
  Component(routes_chat_stream, "routes/chat_stream.py", "Flask", "WS gateway (canonical stream)")
  Component(routes_siri, "routes/siri.py", "Flask", "Fallback STT pipeline")

  Component(chat_realtime, "services/chat_realtime_service.py", "Service", "Tool routing + confirmation gating")
  Component(tool_router, "services/tool_router_service.py", "Service", "Gmail/Calendar/Memory tools")
  Component(cache_sync, "services/cache_sync_service.py", "Service", "Incremental cache refresh")
  Component(turns, "services/turn_coordinator.py", "Service", "Turn lifecycle + idempotency")

  Component(gmail_cache, "storage/gmail_cache_store.py", "Storage", "Gmail cache table")
  Component(cal_cache, "storage/calendar_cache_store.py", "Storage", "Calendar cache table")
  Component(cache_state, "storage/cache_state_store.py", "Storage", "Sync tokens + timestamps")
  Component(turn_store, "storage/turn_store.py", "Storage", "Turn table")
  Component(tool_run_store, "storage/tool_run_store.py", "Storage", "Tool run table")
  Component(confirm_store, "storage/confirmation_store.py", "Storage", "Confirmation table")
}

ContainerDb(supabase, "Supabase", "Postgres", "Profiles, turns, caches, memory")
System_Ext(openai, "OpenAI", "Realtime + text")
System_Ext(google, "Google APIs", "Gmail + Calendar")

Rel(routes_chat_agent, chat_realtime, "calls")
Rel(chat_realtime, tool_router, "executes tools")
Rel(tool_router, gmail_cache, "read/write")
Rel(tool_router, cal_cache, "read/write")
Rel(cache_sync, cache_state, "update")
Rel(cache_sync, gmail_cache, "refresh")
Rel(cache_sync, cal_cache, "refresh")
Rel(turns, turn_store, "persist")
Rel(tool_router, tool_run_store, "persist")
Rel(chat_realtime, confirm_store, "persist")
Rel(tool_router, google, "API calls")
Rel(chat_realtime, openai, "model tools")
Rel(gmail_cache, supabase, "store")
Rel(cal_cache, supabase, "store")
Rel(cache_state, supabase, "store")
Rel(turn_store, supabase, "store")
Rel(tool_run_store, supabase, "store")
Rel(confirm_store, supabase, "store")
```

### Sequence: realtime tool call with confirmation
```mermaid
sequenceDiagram
  participant User
  participant iOS
  participant Realtime
  participant Backend
  participant Google

  User->>iOS: Speak request
  iOS->>Realtime: WebRTC audio
  Realtime-->>iOS: input_transcript.delta
  Realtime-->>iOS: tool_call (gmail_send)
  iOS->>Backend: POST /chat/agent/tool
  Backend-->>iOS: confirmation.request
  iOS->>User: Show confirmation card
  User->>iOS: Confirm
  iOS->>Backend: POST /chat/agent/confirm
  Backend->>Google: Gmail API
  Google-->>Backend: Result
  Backend-->>iOS: tool output
  Realtime-->>iOS: assistant audio + text
```
