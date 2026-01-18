from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from storage.turn_store import create_turn, update_turn
from storage.tool_run_store import create_tool_run, get_tool_run_by_idempotency
from utils.observability import log_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class TurnInfo:
    turn_id: str
    user_id: str
    thread_id: Optional[str]
    session_id: Optional[str]
    input_mode: str
    execution_mode: str
    pipeline: str
    state: str
    started_at: str


class TurnCoordinator:
    def __init__(self) -> None:
        self._inflight: Dict[str, TurnInfo] = {}

    @staticmethod
    def _coerce_uuid(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except Exception:
            return None

    def start_turn(
        self,
        *,
        user_id: str,
        thread_id: Optional[str],
        session_id: Optional[str],
        input_mode: str,
        execution_mode: str,
        pipeline: str,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> TurnInfo:
        turn_id = str(uuid.uuid4())
        safe_user_id = self._coerce_uuid(user_id)
        info = TurnInfo(
            turn_id=turn_id,
            user_id=safe_user_id or user_id,
            thread_id=thread_id,
            session_id=session_id,
            input_mode=input_mode,
            execution_mode=execution_mode,
            pipeline=pipeline,
            state="listening",
            started_at=_now_iso(),
        )
        self._inflight[turn_id] = info
        create_turn({
            "turn_id": turn_id,
            "thread_id": thread_id,
            "user_id": safe_user_id,
            "input_mode": input_mode,
            "execution_mode": execution_mode,
            "pipeline": pipeline,
            "state": info.state,
            "started_at": info.started_at,
            "request_id": request_id,
            "trace_id": trace_id,
            "session_id": self._coerce_uuid(session_id),
        })
        log_event(
            "turn",
            "start_turn",
            session_id=session_id,
            turn_id=turn_id,
            request_id=request_id,
            data={"input_mode": input_mode, "execution_mode": execution_mode, "pipeline": pipeline},
        )
        return info

    def set_state(self, turn_id: str, state: str, request_id: Optional[str] = None) -> None:
        if not turn_id:
            return
        update_turn(turn_id, {"state": state})
        log_event("turn", "set_state", turn_id=turn_id, request_id=request_id, data={"state": state})

    def complete_turn(
        self,
        turn_id: str,
        outcome: str,
        error_code: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        if not turn_id:
            return
        update_turn(
            turn_id,
            {
                "outcome": outcome,
                "error_code": error_code,
                "ended_at": _now_iso(),
            },
        )
        self._inflight.pop(turn_id, None)
        log_event(
            "turn",
            "complete_turn",
            turn_id=turn_id,
            request_id=request_id,
            data={"outcome": outcome, "error_code": error_code},
        )

    def register_tool_call(
        self,
        *,
        turn_id: str,
        tool_name: str,
        step_index: int,
        idempotency_key: str,
        input_payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        existing = get_tool_run_by_idempotency(idempotency_key)
        if existing:
            return existing
        return create_tool_run({
            "tool_run_id": str(uuid.uuid4()),
            "turn_id": turn_id,
            "step_index": step_index,
            "tool_name": tool_name,
            "status": "queued",
            "idempotency_key": idempotency_key,
            "input": input_payload,
            "started_at": _now_iso(),
        })
