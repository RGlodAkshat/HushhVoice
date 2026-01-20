from __future__ import annotations

from flask import Blueprint, request

from config import log
from services.chat_realtime_service import (
    create_chat_realtime_token,
    get_chat_config,
    handle_tool_call,
    confirm_tool_call,
    prefetch_for_hint,
)
from utils.errors import ServiceError
from utils.json_helpers import jerror, jok

chat_agent_bp = Blueprint("chat_agent", __name__)


def _get_user_id() -> str:
    uid = request.args.get("user_id") or request.headers.get("X-User-Id")
    if uid:
        return uid.strip()
    data = request.get_json(force=True, silent=True) or {}
    uid = data.get("user_id")
    return (uid or "dev-anon").strip()


@chat_agent_bp.get("/chat/agent/config")
def chat_agent_config():
    user_id = _get_user_id()
    cfg = get_chat_config(user_id)
    return jok(cfg)


@chat_agent_bp.post("/chat/agent/token")
def chat_agent_token():
    data = request.get_json(force=True, silent=True) or {}
    model = (data.get("model") or "").strip() or None
    ttl_seconds = data.get("ttl_seconds")
    log.info("[ChatAgent] token request model=%s ttl=%s", model, ttl_seconds)
    try:
        out = create_chat_realtime_token(model=model, ttl_seconds=ttl_seconds)
        return jok(out)
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)


@chat_agent_bp.post("/chat/agent/tool")
def chat_agent_tool():
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()
    tool_name = (data.get("tool_name") or "").strip()
    args = data.get("arguments") or {}
    google_token = data.get("google_access_token")
    call_id = (data.get("call_id") or "").strip() or None
    turn_id = (data.get("turn_id") or "").strip() or None
    request_id = request.headers.get("X-Request-Id")

    if not tool_name:
        return jerror("Missing tool_name", 400)

    try:
        output = handle_tool_call(
            user_id=user_id,
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {},
            google_token=google_token,
            request_id=request_id,
            call_id=call_id,
            turn_id=turn_id,
        )
        return jok(output)
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)
    except Exception as e:
        log.exception("chat_agent_tool failed")
        return jerror(str(e), 500)


@chat_agent_bp.post("/chat/agent/confirm")
def chat_agent_confirm():
    data = request.get_json(force=True, silent=True) or {}
    confirmation_id = (data.get("confirmation_request_id") or "").strip()
    user_id = (data.get("user_id") or _get_user_id()).strip()
    tool_name = (data.get("tool_name") or "").strip() or None
    args = data.get("arguments") or {}
    edited_text = data.get("edited_text")
    google_token = data.get("google_access_token")
    call_id = (data.get("call_id") or "").strip() or None
    turn_id = (data.get("turn_id") or "").strip() or None
    request_id = request.headers.get("X-Request-Id")

    if not confirmation_id:
        return jerror("Missing confirmation_request_id", 400)

    try:
        output = confirm_tool_call(
            confirmation_id=confirmation_id,
            user_id=user_id,
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {},
            edited_text=edited_text,
            google_token=google_token,
            request_id=request_id,
            call_id=call_id,
            turn_id=turn_id,
        )
        return jok(output)
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)
    except Exception as e:
        log.exception("chat_agent_confirm failed")
        return jerror(str(e), 500)


@chat_agent_bp.post("/chat/agent/prefetch")
def chat_agent_prefetch():
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()
    google_token = data.get("google_access_token")
    hint = (data.get("hint") or "").strip()

    if not user_id:
        return jerror("Missing user_id", 400)
    if not hint:
        return jok({"ok": True, "prefetch": "noop"})

    try:
        return jok(prefetch_for_hint(user_id=user_id, google_token=google_token, hint=hint))
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)
    except Exception as e:
        log.exception("chat_agent_prefetch failed")
        return jerror(str(e), 500)
