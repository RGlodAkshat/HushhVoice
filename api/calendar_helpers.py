from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from app_context import client, log
from google_helpers import _google_get, _google_post, _iso
from openai_helpers import (
    DEFAULT_SYSTEM,
    _append_task_block,
    _chat_complete,
    _coerce_messages,
    _ensure_system_first,
)


# =========================
# Calendar helpers
# =========================
def calendar_answer_core(
    access_token: str,
    question: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 100,
    incoming_messages: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Shared calendar QA core used by /calendar/answer and Siri.
    """
    if not access_token:
        raise RuntimeError("Missing Google access token")
    q = (question or "").strip()
    if not q:
        raise RuntimeError("Missing 'query'")

    now = dt.datetime.now(dt.timezone.utc)
    tmin = time_min or _iso(now - dt.timedelta(days=14))
    tmax = time_max or _iso(now + dt.timedelta(days=60))

    def list_events_for_calendar(cal_id: str, tmin: str, tmax: str, limit: int) -> list[dict]:
        items = []
        page_token = None
        while True:
            params = {
                "timeMin": tmin,
                "timeMax": tmax,
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": min(250, limit),
            }
            if page_token:
                params["pageToken"] = page_token
            r = _google_get(access_token, f"/calendars/{cal_id}/events", params)
            items.extend(r.get("items", []))
            page_token = r.get("nextPageToken")
            if not page_token or len(items) >= limit:
                break
        return items[:limit]

    # Discover calendars
    cl = _google_get(access_token, "/users/me/calendarList", {"minAccessRole": "reader"})
    calendars = cl.get("items", [])
    if not calendars:
        return {
            "answer": "I can’t see any calendars on this account.",
            "events_used": 0,
        }

    all_events = []
    for c in calendars:
        cal_id = c.get("id")
        cal_name = c.get("summary") or cal_id
        try:
            events = list_events_for_calendar(cal_id, tmin, tmax, max_results)
            if events:
                for e in events:
                    e["_calendar"] = cal_name
                all_events.extend(events)
        except Exception as e:
            log.warning("[CalendarAnswer] Failed for %s: %s", cal_name, e)

    # If nothing found, widen window
    if not all_events:
        wide_min = _iso(now - dt.timedelta(days=90))
        wide_max = _iso(now + dt.timedelta(days=180))
        log.info("[CalendarAnswer] No events; widening window to %s .. %s", wide_min, wide_max)
        for c in calendars:
            cal_id = c.get("id")
            cal_name = c.get("summary") or cal_id
            try:
                events = list_events_for_calendar(cal_id, wide_min, wide_max, max_results)
                for e in events:
                    e["_calendar"] = cal_name
                all_events.extend(events)
            except Exception as e:
                log.warning("[CalendarAnswer] (wide) Failed for %s: %s", cal_name, e)

    def fmt_evt(evt: dict) -> str:
        start = (evt.get("start", {}).get("dateTime") or evt.get("start", {}).get("date") or "")
        end = (evt.get("end", {}).get("dateTime") or evt.get("end", {}).get("date") or "")
        where = evt.get("location") or ""
        attendees = ", ".join(
            [a.get("email", "") for a in evt.get("attendees", []) if a.get("email")]
        )
        calname = evt.get("_calendar", "")
        return (
            f"[{calname}]\n"
            f"Title: {evt.get('summary','(no title)')}\n"
            f"Start: {start}\n"
            f"End: {end}\n"
            f"Location: {where}\n"
            f"Attendees: {attendees}\n"
            f"Notes: {(evt.get('description') or '')}\n"
        )

    context = "\n---\n".join(fmt_evt(e) for e in all_events[:max_results])

    if not client:
        return {
            "answer": f"(offline) You asked: {q}. Fetched {len(all_events)} events.",
            "events_used": len(all_events),
        }

    base_messages = _coerce_messages(incoming_messages) if incoming_messages else []
    messages = _ensure_system_first(base_messages, DEFAULT_SYSTEM)

    system_prompt = "You are CalendarGPT. Answer clearly and helpfully. If uncertain, say so. Keep it crisp."
    messages.append({"role": "system", "content": system_prompt})

    user_prompt = f"User Question:\n{q}\n\nEvents:\n{context}"
    messages = _append_task_block(messages, user_prompt, as_user=True)

    out = _chat_complete(messages, temperature=0.5, max_tokens=600)
    answer = out["content"]
    log.info("[CalendarAnswer] EventsUsed=%d", len(all_events))

    return {
        "answer": answer,
        "events_used": len(all_events),
    }


def calendar_plan_core(
    access_token: str,
    instruction: str,
    confirm: bool = False,
    default_dur: int = 30,
    user_name: str = "",
    incoming_messages: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Shared calendar planning core used by /calendar/plan and Siri.
    When confirm=False: parse natural language into event JSON + human summary.
    When confirm=True: create event in primary calendar and return ids.
    """
    if not access_token:
        raise RuntimeError("Missing Google access token")
    instr = (instruction or "").strip()
    if not instr:
        raise RuntimeError("Missing 'instruction'")

    if not client and not confirm:
        # Offline preview stub
        return {
            "event": {
                "summary": instr[:60],
                "start": "",
                "end": "",
                "timezone": "",
                "attendees": [],
                "location": "",
                "description": "",
                "conference": False,
            },
            "human_summary": "(offline preview)",
        }

    base_messages = _coerce_messages(incoming_messages) if incoming_messages else []
    messages = _ensure_system_first(base_messages, DEFAULT_SYSTEM)

    if not confirm:
        # Preview: parse NL instruction into structured JSON
        system_prompt = (
            "You are CalendarGPT. Parse a natural language instruction into a calendar event JSON.\n"
            "Output STRICTLY valid JSON with keys:\n"
            "{\n"
            '  "summary": "string",                // title\n'
            '  "start": "YYYY-MM-DDTHH:MM:SS",     // local datetime\n'
            '  "end": "YYYY-MM-DDTHH:MM:SS",\n'
            '  "timezone": "IANA string",          // e.g., America/Los_Angeles\n'
            '  "attendees": ["email1", "email2"],\n'
            '  "location": "string",\n'
            '  "description": "string",\n'
            '  "conference": true|false            // request video link\n'
            "}\n"
            f"If the user doesn't specify an end time, default duration is {default_dur} minutes.\n"
            "If timezone is missing, infer conservatively or leave blank.\n"
            "If you omit an explicit offset in the datetime string, that's okay as long as the "
            "format is valid ISO (YYYY-MM-DDTHH:MM:SS); the separate \"timezone\" field will be used."
        )
        messages.append({"role": "system", "content": system_prompt})
        messages = _append_task_block(
            messages,
            f"Instruction:\n{instr}\n\nReturn only JSON. No prose, no backticks.",
            as_user=True,
        )

        out = _chat_complete(messages, temperature=0.4, max_tokens=600)
        import json as _json
        obj = _json.loads((out["content"] or "").strip())

        ev = {
            "summary": obj.get("summary") or "(No title)",
            "start": obj.get("start") or "",
            "end": obj.get("end") or "",
            "timezone": obj.get("timezone") or "",
            "attendees": [
                a for a in (obj.get("attendees") or [])
                if isinstance(a, str) and "@" in a
            ],
            "location": obj.get("location") or "",
            "description": obj.get("description") or "",
            "conference": bool(obj.get("conference", False)),
        }

        hs = (
            f"Title: {ev['summary']}\n"
            f"When: {ev['start']} → {ev['end']}"
            + (f" ({ev['timezone']})" if ev['timezone'] else "")
            + "\n"
            + (f"Where: {ev['location']}\n" if ev['location'] else "")
            + (f"Attendees: {', '.join(ev['attendees'])}\n" if ev['attendees'] else "")
            + (f"Notes: {ev['description']}\n" if ev['description'] else "")
            + ("Video: requested\n" if ev['conference'] else "")
        )
        return {"event": ev, "human_summary": hs}

    # confirm == True -> create event
    ev = incoming_messages  # Not used in confirm branch; kept for signature compatibility
    raise NotImplementedError("Confirm flow should use the route-level implementation.")
