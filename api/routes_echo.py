from __future__ import annotations

import json
import time

from flask import Response, request

from app_context import OPENAI_MODEL, app, client, log
from auth_helpers import verify_google_token_if_enabled
from json_helpers import jerror, jok
from openai_helpers import DEFAULT_SYSTEM, _chat_complete, _coerce_messages, _ensure_system_first


# =========================
# Chat: /echo (+ streaming)
# =========================
@app.post("/echo")
def echo():
    data = request.get_json(force=True, silent=True) or {}
    incoming_messages = _coerce_messages(data.get("messages"))
    user_input = (data.get("query") or "").strip()

    _ = verify_google_token_if_enabled()

    try:
        if incoming_messages:
            messages = _ensure_system_first(incoming_messages, DEFAULT_SYSTEM)
        else:
            if not user_input:
                return jerror("Empty input", 400)
            messages = _ensure_system_first([], DEFAULT_SYSTEM)
            messages.append({"role": "user", "content": user_input})

        out = _chat_complete(messages, temperature=0.6, max_tokens=300)
        if out["offline"]:
            return jok({"response": out["content"]})
        return jok({"response": out["content"]})
    except Exception as e:
        log.exception("Echo error")
        return jerror(str(e), 500)


@app.post("/echo/stream")
def echo_stream():
    data = request.get_json(force=True, silent=True) or {}
    incoming_messages = _coerce_messages(data.get("messages"))
    user_input = (data.get("query") or "").strip()

    _ = verify_google_token_if_enabled()

    if not client:
        def gen_offline():
            yield "data: " + json.dumps({"delta": "(offline) "}) + "\n\n"
            time.sleep(0.2)
            yield "data: " + json.dumps({"delta": (user_input or "[no input]")}) + "\n\n"
            yield "event: done\ndata: {}\n\n"

        return Response(gen_offline(), mimetype="text/event-stream")

    # Build final messages list
    if incoming_messages:
        messages = _ensure_system_first(incoming_messages, DEFAULT_SYSTEM)
    else:
        if not user_input:
            return jerror("Empty input", 400)
        messages = _ensure_system_first([], DEFAULT_SYSTEM)
        messages.append({"role": "user", "content": user_input})

    def generate():
        try:
            with client.chat.completions.with_streaming_response.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.6,
                max_tokens=300,
                stream=True,
            ) as stream:
                for event in stream:
                    if hasattr(event, "choices") and event.choices:
                        delta = getattr(event.choices[0].delta, "content", None)
                        if delta:
                            yield "data: " + json.dumps({"delta": delta}) + "\n\n"
                yield "event: done\ndata: {}\n\n"
        except Exception as e:
            yield "event: error\ndata: " + json.dumps({"message": str(e)}) + "\n\n"

    return Response(generate(), mimetype="text/event-stream")
