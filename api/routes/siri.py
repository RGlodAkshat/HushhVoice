from __future__ import annotations

from flask import Blueprint, request, g

from config import log
from services.tool_router_service import run_agentic_query
from utils.json_helpers import jerror, jok

siri_bp = Blueprint("siri", __name__)


# =========================
# Siri: /siri/ask (iOS + Shortcuts)
# =========================
@siri_bp.post("/siri/ask")
def siri_ask():
    """
    Entry point for iOS App / App Intent "AskHushhVoice".

    Body:
      {
        "prompt": str,
        "locale"?: str,
        "timezone"?: str,
        "tokens"?: {
          "app_jwt"?: str,
          "google_access_token"?: str | null
        }
      }
    """
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jerror("Missing 'prompt'.", 400)

    # 1) App auth (your JWT) – placeholder
    app_jwt = (data.get("tokens", {}) or {}).get("app_jwt")
    if not app_jwt:
        return jerror("Missing app auth.", 401, "unauthorized")
    # TODO: verify app_jwt signature / expiry

    # 2) Optional Google token (enables mail/calendar intents)
    gtoken = (data.get("tokens", {}) or {}).get("google_access_token")

    try:
        user_id = (
            (data.get("user_id") or request.headers.get("X-User-Id") or "").strip()
            or (request.headers.get("X-User-Email") or "siri@local").strip()
        )
        user_email = request.headers.get("X-User-Email") or ""
        out = run_agentic_query(
            prompt=prompt,
            user_id=user_id,
            google_token=gtoken,
            user_email=user_email,
            locale=(data.get("locale") or "").strip() or None,
            timezone=(data.get("timezone") or "").strip() or None,
            request_id=getattr(g, "request_id", None),
        )
        return jok(out)

    except Exception as e:
        log.exception("Siri ask failed")
        msg = "I ran into an error answering that. Please try again in a bit."
        return jok({"speech": msg, "display": msg})
