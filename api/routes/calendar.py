from __future__ import annotations

import uuid

from flask import Blueprint, request

from clients.google_client import _google_post
from clients.openai_client import (
    DEFAULT_SYSTEM,
    _append_task_block,
    _chat_complete,
    _coerce_messages,
    _ensure_system_first,
    client,
)
from config import log
from services.calendar_service import calendar_answer_core, calendar_plan_core
from utils.auth_helpers import get_access_token_from_request
from utils.json_helpers import jerror, jok

calendar_bp = Blueprint("calendar", __name__)


# =========================
# Calendar Answer (web)
# =========================
@calendar_bp.post("/calendar/answer")
def calendar_answer():
    """
    Summarize or answer questions about the user's calendar across ALL calendars.
    Body:
      {
        query: string,
        time_min?: ISO (default: now-14d)
        time_max?: ISO (default: now+60d)
        max_results?: number (default 100),
        calendar_id?: string | null,  # optional; currently unused in core helper
        messages?: [ {role, content}, ... ]
      }
    Header:
      X-Google-Access-Token: <OAuth token with calendar.readonly or calendar.events>
    """
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get("query") or "").strip()
    if not question:
        return jerror("Missing 'query' in request body.", 400)

    access_token = get_access_token_from_request(data)
    if not access_token:
        return jerror("Missing Google access token.", 401, "unauthorized")

    max_results = int(data.get("max_results") or 100)
    time_min = data.get("time_min") or None
    time_max = data.get("time_max") or None
    incoming_messages = data.get("messages") or []

    try:
        result = calendar_answer_core(
            access_token=access_token,
            question=question,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            incoming_messages=incoming_messages,
        )
        return jok(result)
    except Exception as e:
        log.exception("calendar_answer failed")
        return jerror(str(e), 500)


# =========================
# Calendar Plan (web)
# =========================
@calendar_bp.post("/calendar/plan")
def calendar_plan():
    """
    Draft (and optionally create) a calendar event from natural language.
    Body:
      {
        instruction: string,
        confirm?: bool (default false),
        default_duration_minutes?: number (default 30),
        event?: {summary, start, end, timezone, attendees[], location, description, conference?: bool},
        send_updates?: "all"|"externalOnly"|"none",
        messages?: [ {role, content}, ... ]
      }
    Header:
      X-Google-Access-Token: <OAuth token with calendar.events>
      X-User-Name?: optional (for description/signature)
    """
    data = request.get_json(force=True, silent=True) or {}
    instruction = (data.get("instruction") or "").strip()
    if not instruction:
        return jerror("Missing 'instruction' in request body.", 400)

    access_token = get_access_token_from_request(data)
    if not access_token:
        return jerror("Missing Google access token.", 401, "unauthorized")

    confirm = bool(data.get("confirm", False))
    default_dur = int(data.get("default_duration_minutes") or 30)
    user_name = request.headers.get("X-User-Name") or ""
    incoming_messages = data.get("messages") or []

    if not client and not confirm:
        return jok({
            "event": {
                "summary": instruction[:60],
                "start": "",
                "end": "",
                "timezone": "",
                "attendees": [],
                "location": "",
                "description": "",
                "conference": False,
            },
            "human_summary": "(offline preview)",
        })

    try:
        # Preview: use core helper
        if not confirm:
            draft = calendar_plan_core(
                access_token=access_token,
                instruction=instruction,
                confirm=False,
                default_dur=default_dur,
                user_name=user_name,
                incoming_messages=incoming_messages,
            )
            return jok(draft)

        # confirm == True -> create event using Google Calendar
        ev = data.get("event")
        if not ev:
            # As a safety fallback, re-parse the instruction with a leaner prompt
            base_messages = _coerce_messages(incoming_messages)
            messages = _ensure_system_first(base_messages, DEFAULT_SYSTEM)
            system_prompt = "You are CalendarGPT. Parse a natural language instruction into a calendar event JSON."
            messages.append({"role": "system", "content": system_prompt})
            messages = _append_task_block(messages, instruction, as_user=True)
            out = _chat_complete(messages, temperature=0.2, max_tokens=400)
            import json as _json
            ev = _json.loads((out["content"] or "").strip())

        start_obj = {"dateTime": ev.get("start")}
        end_obj = {"dateTime": ev.get("end")}
        if ev.get("timezone"):
            start_obj["timeZone"] = ev["timezone"]
            end_obj["timeZone"] = ev["timezone"]

        g_event = {
            "summary": ev.get("summary") or "(No title)",
            "start": start_obj,
            "end": end_obj,
        }
        if ev.get("location"):
            g_event["location"] = ev["location"]
        if ev.get("description") or user_name:
            desc = ev.get("description") or ""
            if user_name:
                desc = f"{desc}\n\n— {user_name}".strip()
            g_event["description"] = desc
        if ev.get("attendees"):
            g_event["attendees"] = [{"email": a} for a in ev["attendees"]]

        if ev.get("conference"):
            g_event["conferenceData"] = {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        params = {}
        send_updates = data.get("send_updates")
        if send_updates in ("all", "externalOnly", "none"):
            params["sendUpdates"] = send_updates

        created = _google_post(
            access_token,
            "/calendars/primary/events?conferenceDataVersion=1",
            g_event,
        )
        return jok(
            {
                "id": created.get("id"),
                "htmlLink": created.get("htmlLink"),
                "selfLink": created.get("selfLink"),
            }
        )

    except Exception as e:
        log.exception("calendar_plan failed")
        return jerror(str(e), 500)
