from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
import time

from clients.openai_client import DEFAULT_SYSTEM, _ensure_system_first, client
from config import OPENAI_MODEL, log
from services.tool_router_service import run_agentic_query
from services.orchestrator_service import ExecutionModeSelector, Planner, Executor
from services.turn_coordinator import TurnCoordinator
from utils.observability import log_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_TOOL_KEYWORDS = (
    "gmail",
    "email",
    "inbox",
    "calendar",
    "meeting",
    "schedule",
    "event",
)


def _needs_tools(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in _TOOL_KEYWORDS)


def _progress_plan(text: str) -> List[str]:
    lower = text.lower()
    steps: List[str] = []
    if any(k in lower for k in ("gmail", "email", "inbox")):
        steps += ["Checking your inbox...", "Reading recent emails..."]
    if any(k in lower for k in ("calendar", "meeting", "schedule", "event")):
        steps += ["Looking at your calendar...", "Finding free slots..."]
    if "reply" in lower or "respond" in lower:
        steps.append("Drafting a reply...")
    if not steps:
        steps.append("Working on that...")
    return steps


def _chunk_text(text: str, max_len: int = 90) -> Iterable[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: List[str] = []
    for part in parts:
        if not part:
            continue
        if len(part) <= max_len:
            chunks.append(part)
        else:
            start = 0
            while start < len(part):
                end = min(start + max_len, len(part))
                chunks.append(part[start:end])
                start = end
    return chunks


def _stream_basic_completion(prompt: str, retries: int = 2) -> Iterable[str]:
    if not client:
        yield "(offline) " + prompt[:180]
        return
    messages = _ensure_system_first([], DEFAULT_SYSTEM)
    messages.append({"role": "user", "content": prompt})
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            stream = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.6,
                max_tokens=500,
                stream=True,
            )
            for chunk in stream:
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = getattr(chunk.choices[0].delta, "content", None)
                    if delta:
                        yield delta
            return
        except Exception as exc:
            last_error = exc
            log.warning("streaming chat failed attempt=%s error=%s", attempt + 1, exc)
            if attempt < retries:
                time.sleep(0.35 * (attempt + 1))

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=500,
        )
        content = (resp.choices[0].message.content or "").strip()
        if content:
            yield content
            return
    except Exception:
        log.exception("fallback chat failed after stream error=%s", last_error)

    yield "I ran into a problem streaming that response."


@dataclass
class SessionContext:
    session_id: str
    user_id: str
    request_id: Optional[str]


class SessionState:
    def __init__(self) -> None:
        self.seq = 0
        self.turn_seq = 0
        self.turn_id: Optional[str] = None
        self.pending_prompt: Optional[str] = None
        self.pending_confirmation_id: Optional[str] = None

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def next_turn_seq(self) -> int:
        self.turn_seq += 1
        return self.turn_seq

    def reset_turn(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self.turn_seq = 0


class ChatGateway:
    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._turns = TurnCoordinator()
        self._mode_selector = ExecutionModeSelector()
        self._planner = Planner()
        self._executor = Executor()

    def _session_state(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState()
        return self._sessions[session_id]

    def _event(self, ctx: SessionContext, state: SessionState, event_type: str, payload: Dict[str, Any], role: Optional[str] = None) -> Dict[str, Any]:
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "ts": _now_iso(),
            "session_id": ctx.session_id,
            "turn_id": state.turn_id,
            "message_id": None,
            "seq": state.next_seq(),
            "turn_seq": state.next_turn_seq(),
            "role": role,
            "payload": payload,
        }

    def handle_event(self, raw: Dict[str, Any], ctx: SessionContext) -> Iterable[Dict[str, Any]]:
        event_type = raw.get("event_type") or raw.get("type") or ""
        payload = raw.get("payload") or {}
        state = self._session_state(ctx.session_id)

        log.info("[ChatGateway] event_in type=%s session=%s turn=%s", event_type, ctx.session_id, state.turn_id)
        log_event(
            "gateway",
            "event_in",
            session_id=ctx.session_id,
            turn_id=state.turn_id,
            request_id=ctx.request_id,
            data={"event_type": event_type},
        )

        if event_type == "session.ping":
            yield self._event(ctx, state, "state.change", {"from": "idle", "to": "idle", "reason": "ping"}, role="system")
            return

        if event_type == "user.interrupt":
            if state.turn_id:
                self._turns.set_state(state.turn_id, "cancelled", request_id=ctx.request_id)
                self._turns.complete_turn(state.turn_id, "cancelled", request_id=ctx.request_id)
            yield self._event(ctx, state, "turn.cancelled", {"cancel_turn_id": state.turn_id}, role="system")
            state.turn_id = None
            state.pending_prompt = None
            state.pending_confirmation_id = None
            return

        if event_type in ("text.input", "audio.end"):
            text = str(payload.get("text") or "").strip()
            if not text:
                return
            if state.turn_id:
                self._turns.set_state(state.turn_id, "cancelled", request_id=ctx.request_id)
                self._turns.complete_turn(state.turn_id, "cancelled", request_id=ctx.request_id)
                yield self._event(ctx, state, "turn.cancelled", {"cancel_turn_id": state.turn_id}, role="system")
                state.turn_id = None
                state.pending_prompt = None
                state.pending_confirmation_id = None
            input_mode = "voice" if payload.get("source") == "voice" or event_type == "audio.end" else "text"
            plan = self._planner.build_plan(text)
            tool_count = len(plan.steps)
            has_write = any(step.action_level == "write" for step in plan.steps)
            mode = self._mode_selector.choose(
                realtime_healthy=True,
                tool_count=tool_count,
                has_write=has_write,
                ambiguity=False,
                long_running=False,
            )
            execution_mode = mode.execution_mode
            turn = self._turns.start_turn(
                user_id=ctx.user_id,
                thread_id=None,
                session_id=ctx.session_id,
                input_mode=input_mode,
                execution_mode=execution_mode,
                pipeline=mode.pipeline,
                request_id=ctx.request_id,
            )
            state.reset_turn(turn.turn_id)
            self._turns.set_state(turn.turn_id, "thinking", request_id=ctx.request_id)
            yield self._event(ctx, state, "turn.start", {"input_mode": turn.input_mode}, role="system")
            yield self._event(ctx, state, "state.change", {"from": "listening", "to": "thinking", "reason": "route"}, role="system")

            if execution_mode == "backend_orchestrated" and has_write:
                state.pending_prompt = text
                confirmation = self._executor.confirmation_gate.request_confirmation(
                    turn_id=turn.turn_id,
                    action_type="write_action",
                    preview={"summary": "This request may send email or create calendar events. Confirm before executing."},
                )
                state.pending_confirmation_id = confirmation
                self._turns.set_state(turn.turn_id, "awaiting_confirmation", request_id=ctx.request_id)
                yield self._event(ctx, state, "state.change", {"from": "thinking", "to": "awaiting_confirmation", "reason": "confirm"}, role="system")
                yield self._event(ctx, state, "confirmation.request", {
                    "confirmation_request_id": confirmation,
                    "action_type": "write_action",
                    "preview": "This request may send email or create calendar events. Confirm to proceed.",
                }, role="system")
                return

            if execution_mode == "backend_orchestrated":
                self._turns.set_state(turn.turn_id, "executing_tools", request_id=ctx.request_id)
                yield self._event(ctx, state, "state.change", {"from": "thinking", "to": "executing_tools", "reason": "tools"}, role="system")
                for step in _progress_plan(text):
                    yield self._event(ctx, state, "tool_call.progress", {"message": step, "status": "running"}, role="assistant")
                start_ts = time.time()
                result = run_agentic_query(
                    prompt=text,
                    user_id=ctx.user_id,
                    google_token=payload.get("google_access_token"),
                    request_id=ctx.request_id,
                )
                log_event(
                    "gateway",
                    "agentic_query_completed",
                    session_id=ctx.session_id,
                    turn_id=turn.turn_id,
                    request_id=ctx.request_id,
                    data={"elapsed_ms": int((time.time() - start_ts) * 1000)},
                )
                reply = (result.get("display") or result.get("speech") or "").strip()
                if not reply:
                    reply = "I couldn't generate a response."
                yield self._event(ctx, state, "state.change", {"from": "executing_tools", "to": "speaking", "reason": "answer"}, role="system")
                for chunk in _chunk_text(reply):
                    yield self._event(ctx, state, "assistant_text.delta", {"text": chunk}, role="assistant")
            else:
                yield self._event(ctx, state, "state.change", {"from": "thinking", "to": "speaking", "reason": "answer"}, role="system")
                for delta in _stream_basic_completion(text):
                    yield self._event(ctx, state, "assistant_text.delta", {"text": delta}, role="assistant")

            yield self._event(ctx, state, "assistant_text.final", {}, role="assistant")
            yield self._event(ctx, state, "turn.end", {"outcome": "success", "error_code": None}, role="system")
            self._turns.complete_turn(turn.turn_id, "success", request_id=ctx.request_id)
            return

        if event_type == "confirm.response":
            decision = (payload.get("decision") or "").lower()
            if decision != "accept":
                if state.turn_id:
                    self._turns.set_state(state.turn_id, "cancelled", request_id=ctx.request_id)
                    self._turns.complete_turn(state.turn_id, "cancelled", request_id=ctx.request_id)
                yield self._event(ctx, state, "turn.cancelled", {"cancel_turn_id": state.turn_id}, role="system")
                state.turn_id = None
                state.pending_prompt = None
                state.pending_confirmation_id = None
                return

            if not state.pending_prompt:
                yield self._event(ctx, state, "state.change", {"from": "awaiting_confirmation", "to": "executing_tools", "reason": "confirm"}, role="system")
                return

            text = state.pending_prompt
            self._turns.set_state(state.turn_id, "executing_tools", request_id=ctx.request_id)
            yield self._event(ctx, state, "state.change", {"from": "awaiting_confirmation", "to": "executing_tools", "reason": "confirm"}, role="system")
            for step in _progress_plan(text):
                yield self._event(ctx, state, "tool_call.progress", {"message": step, "status": "running"}, role="assistant")
            start_ts = time.time()
            result = run_agentic_query(
                prompt=text,
                user_id=ctx.user_id,
                google_token=payload.get("google_access_token"),
                request_id=ctx.request_id,
            )
            log_event(
                "gateway",
                "agentic_query_completed",
                session_id=ctx.session_id,
                turn_id=state.turn_id,
                request_id=ctx.request_id,
                data={"elapsed_ms": int((time.time() - start_ts) * 1000)},
            )
            reply = (result.get("display") or result.get("speech") or "").strip()
            if not reply:
                reply = "I couldn't generate a response."
            yield self._event(ctx, state, "state.change", {"from": "executing_tools", "to": "speaking", "reason": "answer"}, role="system")
            for chunk in _chunk_text(reply):
                yield self._event(ctx, state, "assistant_text.delta", {"text": chunk}, role="assistant")
            yield self._event(ctx, state, "assistant_text.final", {}, role="assistant")
            yield self._event(ctx, state, "turn.end", {"outcome": "success", "error_code": None}, role="system")
            self._turns.complete_turn(state.turn_id, "success", request_id=ctx.request_id)
            state.pending_prompt = None
            state.pending_confirmation_id = None
            return

        return
