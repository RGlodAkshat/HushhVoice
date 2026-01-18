from __future__ import annotations

import uuid
from typing import Any, Dict

from config import log
from services.tool_router_service import TOOL_SPECS, ToolContext
from storage.tool_run_store import create_tool_run, get_tool_run_by_idempotency
from utils.observability import log_event


READ_ONLY_TOOLS = {
    "gmail_search",
    "calendar_list_events",
    "calendar_find_availability",
    "profile_get",
    "memory_search",
}


def run_read_only_tool(
    *,
    tool_name: str,
    args: Dict[str, Any],
    ctx: ToolContext,
    turn_id: str,
    step_index: int,
) -> Dict[str, Any]:
    if tool_name not in READ_ONLY_TOOLS:
        return {"ok": False, "error": {"code": "read_only_blocked", "message": "Tool not allowed in read-only mode."}}

    spec = TOOL_SPECS.get(tool_name)
    if not spec:
        return {"ok": False, "error": {"code": "unknown_tool", "message": "Unknown tool."}}

    idempotency_key = f"{turn_id}:{tool_name}:{step_index}"
    existing = get_tool_run_by_idempotency(idempotency_key)
    if existing:
        log.info("[ToolRouter] idempotent hit tool=%s turn=%s", tool_name, turn_id)
        return {
            "ok": True,
            "cached": True,
            "tool_run_id": existing.get("tool_run_id"),
            "data": existing.get("output_summary") or {},
        }

    tool_run_id = str(uuid.uuid4())
    create_tool_run({
        "tool_run_id": tool_run_id,
        "turn_id": turn_id,
        "step_index": step_index,
        "tool_name": tool_name,
        "status": "running",
        "idempotency_key": idempotency_key,
        "input": args,
    })

    log_event(
        "tool",
        "run_read_only_tool",
        turn_id=turn_id,
        data={"tool_name": tool_name, "step_index": step_index, "idempotency_key": idempotency_key},
    )
    log.info("[ToolRouter] run tool=%s turn=%s", tool_name, turn_id)
    result = spec.handler(args, ctx)
    return {
        "ok": bool(result.get("ok", False)),
        "tool_run_id": tool_run_id,
        "data": result.get("data") or result.get("error") or {},
    }
