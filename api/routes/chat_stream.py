from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from flask import request
from flask_sock import Sock

from config import log
from services.chat_gateway import ChatGateway, SessionContext
from storage.session_store import create_session, update_session
from utils.observability import log_event


sock = Sock()
gateway = ChatGateway()


def init_chat_stream(app) -> None:
    sock.init_app(app)


@sock.route("/chat/stream")
def chat_stream(ws) -> None:
    session_token = request.args.get("session_token") or request.headers.get("X-Session-Token") or ""
    user_id = request.headers.get("X-User-Id") or "dev-anon"
    session_id = request.args.get("session_id") or str(uuid.uuid4())
    ctx = SessionContext(session_id=session_id, user_id=user_id, request_id=request.headers.get("X-Request-Id"))

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    user_id_safe = None
    try:
        user_id_safe = str(uuid.UUID(user_id))
    except Exception:
        user_id_safe = None

    create_session({
        "session_id": session_id,
        "user_id": user_id_safe,
        "started_at": now_iso,
    })

    log_event(
        "gateway",
        "ws_connect",
        session_id=session_id,
        request_id=ctx.request_id,
        data={"user_id": user_id, "has_session_token": bool(session_token)},
    )
    log.info("[ChatStream] connected session=%s user=%s", session_id, user_id)

    while True:
        raw = ws.receive()
        if raw is None:
            break
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            event: Dict[str, Any] = json.loads(raw)
        except Exception:
            log_event("gateway", "ws_bad_json", session_id=session_id, request_id=ctx.request_id)
            continue

        for resp in gateway.handle_event(event, ctx):
            ws.send(json.dumps(resp))

    update_session(session_id, {"last_seen_at": now_iso})
    log_event("gateway", "ws_disconnect", session_id=session_id, request_id=ctx.request_id)
    log.info("[ChatStream] disconnected session=%s", session_id)
