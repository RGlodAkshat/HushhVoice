from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import log
from services.onboarding_service import REALTIME_MODEL, create_realtime_token
from services.cache_sync_service import refresh_calendar_cache, refresh_gmail_cache
from storage.profile_store import load_profile
from services.tool_router_service import ToolContext, build_realtime_tools_schema, run_tool_by_name
from storage.tool_run_store import create_tool_run, get_tool_run_by_idempotency, update_tool_run
from storage.confirmation_store import create_confirmation, get_confirmation, update_confirmation
from utils.errors import ServiceError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


WRITE_TOOLS = {"gmail_send", "calendar_create_event"}


def get_chat_config(user_id: str) -> Dict[str, Any]:
    profile = load_profile(user_id) or {}
    user_name = (profile.get("full_name") or "").strip()
    user_email = (profile.get("email") or "").strip()

    instructions = (
        "You are HushhVoice — a private, consent-first AI copilot. "
        "Be concise, conversational, and ask for clarification only when needed. "
        "You have tools for Gmail, Calendar, and Memory. "
        "Whenever the user asks about email/inbox, call gmail_search. "
        "Whenever the user asks about meetings/schedule/calendar, call calendar_list_events "
        "or calendar_find_availability. "
        "Use memory_search to recall user preferences or facts. "
        "Never send email or create calendar events without explicit confirmation from the user. "
        "If a tool returns missing_google_token, ask the user to connect Google. "
        f"UserName: {user_name or 'unknown'}. UserEmail: {user_email or 'unknown'}."
    )

    cfg = {
        "agent": {"name": "HushhVoice"},
        "user_id": user_id,
        "realtime": {
            "model": REALTIME_MODEL,
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.6,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 700,
                "create_response": False,
                "interrupt_response": True,
            },
        },
        "tools": build_realtime_tools_schema(),
        "instructions": instructions,
    }
    try:
        td = cfg["realtime"]["turn_detection"]
        log.info("[VOICE_DBG][BackendConfig] threshold=%s type=%s", td.get("threshold"), type(td.get("threshold")))
    except Exception:
        log.exception("[VOICE_DBG][BackendConfig] threshold_log_failed")
    return cfg


def create_chat_realtime_token(model: Optional[str], ttl_seconds: Optional[int]) -> Dict[str, Any]:
    return create_realtime_token(model=model or REALTIME_MODEL, ttl_seconds=ttl_seconds)


def prefetch_for_hint(
    *,
    user_id: str,
    google_token: Optional[str],
    hint: str,
) -> Dict[str, Any]:
    if not google_token:
        return {"ok": False, "reason": "missing_google_token"}
    lower = (hint or "").lower()
    wants_gmail = any(k in lower for k in ("gmail", "email", "inbox", "mail"))
    wants_calendar = any(k in lower for k in ("calendar", "meeting", "schedule", "event"))

    if not wants_gmail and not wants_calendar:
        return {"ok": True, "prefetch": "noop"}

    import threading

    def _run():
        try:
            if wants_gmail:
                refresh_gmail_cache(user_id, google_token or "", query="")
            if wants_calendar:
                refresh_calendar_cache(user_id, google_token or "")
        except Exception:
            log.exception("prefetch failed")

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "prefetch": {"gmail": wants_gmail, "calendar": wants_calendar}}


def _preview_for_write(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name == "gmail_send":
        return {
            "to": args.get("to") or args.get("to_email") or args.get("recipient"),
            "subject": args.get("subject"),
            "body": args.get("body"),
            "cc": args.get("cc"),
            "bcc": args.get("bcc"),
        }
    if tool_name == "calendar_create_event":
        return {
            "summary": args.get("summary") or "(No title)",
            "start": args.get("start"),
            "end": args.get("end"),
            "attendees": args.get("attendees") or [],
            "timezone": args.get("timezone"),
        }
    return {"tool": tool_name, "arguments": args}


def _idempotency_key(call_id: Optional[str], tool_name: str, turn_id: Optional[str]) -> Optional[str]:
    if call_id:
        return call_id
    if turn_id:
        return f"{turn_id}:{tool_name}"
    return None


def handle_tool_call(
    *,
    user_id: str,
    tool_name: str,
    args: Dict[str, Any],
    google_token: Optional[str],
    request_id: Optional[str],
    call_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> Dict[str, Any]:
    ctx = ToolContext(
        user_id=user_id,
        google_token=google_token,
        user_email=None,
        locale=None,
        timezone=None,
        request_id=request_id,
    )
    idempotency_key = _idempotency_key(call_id, tool_name, turn_id)
    existing = get_tool_run_by_idempotency(idempotency_key) if idempotency_key else None
    if existing and existing.get("output_summary"):
        cached = existing["output_summary"]
        if isinstance(cached, dict) and cached.get("requires_confirmation"):
            cached["cached"] = True
            return cached
        return {"output": cached, "cached": True}

    if tool_name in WRITE_TOOLS:
        preview = _preview_for_write(tool_name, args)
        confirmation_id = str(uuid.uuid4())
        create_confirmation({
            "confirmation_request_id": confirmation_id,
            "turn_id": turn_id,
            "action_type": tool_name,
            "preview": preview,
            "status": "pending",
            "created_at": _now_iso(),
        })
        output = {
            "requires_confirmation": True,
            "confirmation_request_id": confirmation_id,
            "action_type": tool_name,
            "preview": preview,
        }
        if idempotency_key:
            tool_run_id = str(uuid.uuid4())
            create_tool_run({
                "tool_run_id": tool_run_id,
                "turn_id": turn_id,
                "step_index": 0,
                "tool_name": tool_name,
                "status": "awaiting_confirmation",
                "idempotency_key": idempotency_key,
                "input": args,
                "output_summary": output,
            })
        return output

    result = run_tool_by_name(tool_name, args, ctx)
    if idempotency_key:
        tool_run_id = str(uuid.uuid4())
        create_tool_run({
            "tool_run_id": tool_run_id,
            "turn_id": turn_id,
            "step_index": 0,
            "tool_name": tool_name,
            "status": "completed",
            "idempotency_key": idempotency_key,
            "input": args,
            "output_summary": result,
        })
    return {"output": result}


def confirm_tool_call(
    *,
    confirmation_id: str,
    user_id: str,
    tool_name: Optional[str],
    args: Dict[str, Any],
    edited_text: Optional[str] = None,
    google_token: Optional[str],
    request_id: Optional[str],
    call_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> Dict[str, Any]:
    record = get_confirmation(confirmation_id)
    if record:
        update_confirmation(confirmation_id, {"status": "accepted", "resolved_at": _now_iso()})
        if not tool_name:
            tool_name = record.get("action_type")
        if not args:
            preview = record.get("preview") or {}
            if isinstance(preview, dict):
                args = preview

    if not tool_name:
        raise ServiceError("Missing tool_name for confirmation", 400)

    if edited_text and tool_name == "gmail_send":
        args = dict(args or {})
        args["body"] = edited_text

    ctx = ToolContext(
        user_id=user_id,
        google_token=google_token,
        user_email=None,
        locale=None,
        timezone=None,
        request_id=request_id,
    )
    idempotency_key = _idempotency_key(call_id, tool_name, turn_id)
    existing = get_tool_run_by_idempotency(idempotency_key) if idempotency_key else None
    if existing and existing.get("output_summary"):
        return {"output": existing["output_summary"], "cached": True}

    result = run_tool_by_name(tool_name, args, ctx)
    if idempotency_key:
        tool_run_id = existing.get("tool_run_id") if existing else str(uuid.uuid4())
        if not existing:
            create_tool_run({
                "tool_run_id": tool_run_id,
                "turn_id": turn_id,
                "step_index": 0,
                "tool_name": tool_name,
                "status": "completed",
                "idempotency_key": idempotency_key,
                "input": args,
                "output_summary": result,
            })
        else:
            update_tool_run(tool_run_id, {"status": "completed", "output_summary": result, "finished_at": _now_iso()})
    return {"output": result}
