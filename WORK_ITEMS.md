# HushhVoice Work Items (Testing Branch)

This list captures the work still needed to take the current chat stack from testing to production-grade. It is grouped so multiple devs can work in parallel without stepping on each other.

## 1) Backend Streaming Core
- Fix any remaining OpenAI streaming edge cases (SDK version differences, reconnects).
- Add backpressure handling (rate-limit streaming events if client is slow).
- Emit `assistant_audio.*` events once streaming TTS is available.

## 2) Orchestrator + Tool Execution
- Replace heuristic planner with a real tool planner that:
  - extracts entities (recipients, time windows, meeting titles)
  - emits missing field questions before tool execution
- Add write-action confirmation gates with previews (email body, calendar details).
- Add idempotency keys for Gmail/Calendar write calls.

## 3) Tool Progress & Reliability
- Emit real tool step progress from the executor (not static text).
- Add job queue for long-running tasks (summarize 200 emails, large attachment parse).
- Implement tool retries with exponential backoff and partial-success summaries.

## 4) Supabase Persistence
- Create/verify tables: `chat_turns`, `tool_runs`, `confirmation_requests`, `sessions`, `memories`.
- Add RLS policies + service role usage guidelines.
- Add cleanup/retention policies for long-term storage.

## 5) iOS Voice Duplex + UX
- Confirm mic pause/resume around assistant playback in all edge cases.
- Add explicit state label near the bottom bar (Listening/Thinking/Speaking).
- Add “Jump to Live” polish and auto-scroll guard rails.
- Ensure streaming markdown is smooth and doesn’t re-layout excessively.

## 6) Observability
- Track end-of-speech → first audio byte latency.
- Track tool latency per tool.
- Log turn_id/session_id/request_id on every step.

## 7) QA / Testing
- Add Python tests for gateway event ordering + cancellation.
- Add iOS unit tests for message model and markdown rendering.
- Run manual tests for:
  - barge-in
  - confirmation flow
  - long emails + multi-tool requests

## 8) Deployment Readiness
- Add env validation for OpenAI/Supabase credentials.
- Add a streaming fallback mode toggle.
- Document production config for WebSocket hosting.
