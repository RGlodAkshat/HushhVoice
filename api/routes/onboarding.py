from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, request

from config import log
from services.onboarding_service import (
    REALTIME_MODEL,
    create_realtime_token,
    get_config,
    get_state_debug,
    handle_tool,
    reset_state,
    sync_state,
)
from utils.errors import ServiceError
from utils.json_helpers import jerror, jok

onboarding_bp = Blueprint("onboarding", __name__)


def _get_user_id() -> str:
    uid = request.args.get("user_id") or request.headers.get("X-User-Id")
    if uid:
        return uid.strip()
    data = request.get_json(force=True, silent=True) or {}
    uid = data.get("user_id")
    return (uid or "dev-anon").strip()


@onboarding_bp.get("/onboarding/agent/config")
def onboarding_agent_config():
    user_id = _get_user_id()
    log.info("[Onboarding] config user_id=%s", user_id)
    cfg = get_config(user_id)
    return jok(cfg)


@onboarding_bp.post("/onboarding/agent/token")
def onboarding_agent_token():
    """
    Creates ephemeral client_secret for WebRTC Realtime.
    iOS uses it as Bearer token to POST SDP to /v1/realtime/calls.
    """
    data = request.get_json(force=True, silent=True) or {}
    model = (data.get("model") or REALTIME_MODEL).strip()
    ttl_seconds = data.get("ttl_seconds")
    log.info("[Onboarding] token request model=%s ttl=%s", model, ttl_seconds)

    try:
        out = create_realtime_token(model=model, ttl_seconds=ttl_seconds)
        return jok(out)
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)


@onboarding_bp.post("/onboarding/agent/tool")
def onboarding_agent_tool():
    """
    iOS forwards tool calls here.
    Body:
      { user_id: "...", tool_name: "...", arguments: {...} }

    Returns:
      jok({ output: {...} })
    """
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()
    tool_name = (data.get("tool_name") or "").strip()
    args = data.get("arguments") or {}

    if not tool_name:
        return jerror("Missing tool_name", 400)

    try:
        output = handle_tool(user_id=user_id, tool_name=tool_name, args=args)
        return jok({"output": output})
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)
    except Exception as e:
        log.exception("onboarding_agent_tool failed")
        return jerror(str(e), 500)


@onboarding_bp.get("/onboarding/agent/state")
def onboarding_agent_state():
    """Debug endpoint to inspect state."""
    user_id = _get_user_id()
    return jok(get_state_debug(user_id))


@onboarding_bp.post("/onboarding/agent/sync")
def onboarding_agent_sync():
    """
    Sync onboarding state to Supabase after the summary is shown.
    Body:
      { user_id: "...", state?: {...} }
    """
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()
    incoming_state = data.get("state")

    try:
        out = sync_state(user_id=user_id, incoming_state=incoming_state if isinstance(incoming_state, dict) else None)
        return jok(out)
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)


@onboarding_bp.post("/onboarding/agent/reset")
def onboarding_agent_reset():
    """Dev helper: reset state for a user."""
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()

    out = reset_state(user_id)
    return jok(out)
