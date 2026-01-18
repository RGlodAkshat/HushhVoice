from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.chat_tool_router import run_read_only_tool
from storage.confirmation_store import create_confirmation
from storage.tool_run_store import update_tool_run
from utils.observability import log_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ExecutionMode:
    pipeline: str
    execution_mode: str


class ExecutionModeSelector:
    def choose(
        self,
        *,
        realtime_healthy: bool,
        tool_count: int,
        has_write: bool,
        ambiguity: bool,
        long_running: bool,
    ) -> ExecutionMode:
        pipeline = "realtime" if realtime_healthy else "classic_fallback"
        if tool_count >= 2 or has_write or ambiguity or long_running:
            return ExecutionMode(pipeline=pipeline, execution_mode="backend_orchestrated")
        return ExecutionMode(pipeline=pipeline, execution_mode="direct_response")


@dataclass
class PlanStep:
    step_index: int
    tool_name: str
    args: Dict[str, Any]
    action_level: str
    requires_confirmation: bool = False


@dataclass
class Plan:
    plan_id: str
    steps: List[PlanStep] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    ambiguity: Dict[str, Any] = field(default_factory=dict)


class Planner:
    def build_plan(self, intent: str, args: Optional[Dict[str, Any]] = None) -> Plan:
        text = (intent or "").lower()
        steps: List[PlanStep] = []
        step_index = 1

        if any(k in text for k in ("email", "gmail", "inbox")):
            steps.append(PlanStep(
                step_index=step_index,
                tool_name="gmail_search",
                args={"query": intent, "max_results": 5},
                action_level="read",
            ))
            step_index += 1

        if any(k in text for k in ("calendar", "schedule", "meeting", "event")):
            steps.append(PlanStep(
                step_index=step_index,
                tool_name="calendar_list_events",
                args={"max_results": 10},
                action_level="read",
            ))
            step_index += 1

        if any(k in text for k in ("send", "reply", "email him", "email her")):
            steps.append(PlanStep(
                step_index=step_index,
                tool_name="gmail_send",
                args={},
                action_level="write",
                requires_confirmation=True,
            ))
            step_index += 1

        if any(k in text for k in ("schedule", "create meeting", "create event")):
            steps.append(PlanStep(
                step_index=step_index,
                tool_name="calendar_create_event",
                args={},
                action_level="write",
                requires_confirmation=True,
            ))

        return Plan(plan_id=str(uuid.uuid4()), steps=steps, missing_fields=[], ambiguity={})


class ConfirmationGate:
    def request_confirmation(self, turn_id: str, action_type: str, preview: Dict[str, Any]) -> str:
        confirmation_id = str(uuid.uuid4())
        create_confirmation({
            "confirmation_request_id": confirmation_id,
            "turn_id": turn_id,
            "action_type": action_type,
            "preview": preview,
            "status": "pending",
            "created_at": _now_iso(),
        })
        return confirmation_id


class Executor:
    def __init__(self) -> None:
        self.confirmation_gate = ConfirmationGate()

    def execute_plan(
        self,
        *,
        turn_id: str,
        steps: List[PlanStep],
        tool_ctx: Any,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []

        for step in steps:
            if step.requires_confirmation:
                confirmation_id = self.confirmation_gate.request_confirmation(
                    turn_id=turn_id,
                    action_type=step.tool_name,
                    preview={"tool": step.tool_name, "args": step.args},
                )
                log_event(
                    "confirmation",
                    "request",
                    turn_id=turn_id,
                    request_id=request_id,
                    data={"confirmation_request_id": confirmation_id, "tool": step.tool_name},
                )
                return {"status": "awaiting_confirmation", "confirmation_request_id": confirmation_id}

            tool_result = run_read_only_tool(
                tool_name=step.tool_name,
                args=step.args,
                ctx=tool_ctx,
                turn_id=turn_id,
                step_index=step.step_index,
            )
            results.append(tool_result)

            if tool_result.get("tool_run_id"):
                update_tool_run(tool_result["tool_run_id"], {"status": "completed", "finished_at": _now_iso()})

        return {"status": "completed", "results": results}
