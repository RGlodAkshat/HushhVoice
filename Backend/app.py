# app.py
from __future__ import annotations

import json
import os
import time
import uuid
import logging
from typing import Dict, Any, List, Tuple, Optional
from flask_cors import cross_origin

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_cors import cross_origin
from dotenv import load_dotenv
from openai import OpenAI

# Gmail helpers (you already have these files)
from agents.email_assistant.gmail_fetcher import fetch_recent_emails, send_email
from agents.email_assistant.reply_helper import generate_reply_from_inbox
from agents.email_assistant.helper_functions import build_email_context
from agents.email_assistant.helper_functions import trim_email_fields

# === Optional: Google ID token verification (independent from Gmail access token) ===
VERIFY_GOOGLE_TOKEN = os.getenv("VERIFY_GOOGLE_TOKEN", "false").lower() in ("1", "true", "yes")
if VERIFY_GOOGLE_TOKEN:
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
    except Exception:
        VERIFY_GOOGLE_TOKEN = False  # graceful fallback


# =========================
# Config & Initialization
# =========================
load_dotenv()

APP_NAME = os.getenv("APP_NAME", "HushhVoice API")
APP_VERSION = os.getenv("APP_VERSION", "0.4.0")
PORT = int(os.getenv("PORT", "5000"))
DEBUG = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

MEMORY_PATH = os.getenv("MEMORY_PATH", "data/memory.json")
os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "hushh_secret_🔥")
CORS(app, supports_credentials=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hushhvoice")

client: Optional[OpenAI] = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)





    import datetime as dt
import requests

GOOGLE_CAL_BASE = "https://www.googleapis.com/calendar/v3"

def _google_get(access_token: str, path: str, params: dict):
    url = f"{GOOGLE_CAL_BASE}{path}"
    r = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, params=params, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Google GET {path} -> {r.status_code} {r.text}")
    return r.json()

def _google_post(access_token: str, path: str, json_body: dict):
    url = f"{GOOGLE_CAL_BASE}{path}"
    r = requests.post(url, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }, json=json_body, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Google POST {path} -> {r.status_code} {r.text}")
    return r.json()

def _iso(dt_obj: dt.datetime) -> str:
    # naive → utc iso
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
    return dt_obj.isoformat().replace("+00:00", "Z")



# =========================
# Helpers
# =========================
def jerror(message: str, status: int = 400, code: str = "bad_request") -> Tuple[Response, int]:
    rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    return jsonify({"ok": False, "error": {"code": code, "message": message}, "request_id": rid}), status


def jok(data: Any, status: int = 200) -> Tuple[Response, int]:
    rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    return jsonify({"ok": True, "data": data, "request_id": rid}), status


def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def verify_google_token_if_enabled() -> Optional[Dict[str, Any]]:
    """Verifies Google ID token when enabled. Independent from Gmail access token."""
    if not VERIFY_GOOGLE_TOKEN:
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        payload = id_token.verify_oauth2_token(token, google_requests.Request())
        return payload  # contains 'email', etc.
    except Exception as e:
        log.warning("Google ID token verification failed: %s", e)
        return None


def get_access_token_from_request(data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Gmail requires an **OAuth access token** with appropriate scopes.
    We accept it either in header 'X-Google-Access-Token' or JSON body 'access_token'.
    """
    token = request.headers.get("X-Google-Access-Token")
    if token:
        return token.strip()
    if data:
        t = (data.get("access_token") or "").strip()
        if t:
            return t
    return None




# =========================
# Error Handlers
# =========================
@app.errorhandler(404)
def not_found(_):
    return jerror("Route not found", 404, "not_found")


@app.errorhandler(500)
def internal(_):
    return jerror("Internal server error", 500, "internal_error")


# =========================
# Meta / Health
# =========================
@app.get("/health")
def health():
    return jok({
        "name": APP_NAME,
        "version": APP_VERSION,
        "openai": bool(client),
        "verify_google_token": VERIFY_GOOGLE_TOKEN
    })


@app.get("/version")
def version():
    return jok({"name": APP_NAME, "version": APP_VERSION})


# =========================
# Intent Classifier
# =========================
@app.post("/intent/classify")
def intent_classify_route():
    data = request.get_json(force=True, silent=True) or {}
    user_text = (data.get("query") or "").strip()
    if not user_text:
        return jok({"intent": "general"})

    # --- OpenAI-based classification (same logic you had, wrapped to return JSON) ---
    intent = "general"
    try:
        tools = [{
            "type": "function",
            "name": "classify_intent",
            "description": "Classify the user's query into one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": [
                            "read_email",
                            "send_email",
                            "schedule_event",
                            "calendar_answer",
                            "health",
                            "general"
                        ]
                    }
                },
                "required": ["intent"],
                "additionalProperties": False
            },
            "strict": True
        }]

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict intent classifier for a personal AI assistant.\n"
                        "Classify user queries into: read_email, send_email, schedule_event, "
                        "calendar_answer, health, general."
                    )
                },
                {"role": "user", "content": user_text},
            ],
            tools=tools,
            tool_choice={"type": "function", "name": "classify_intent"},
        )

        for item in resp.output:
            if item.type == "function_call" and item.name == "classify_intent":
                import json as _json
                args = _json.loads(item.arguments)
                intent = args.get("intent", "general")
                break
    except Exception as e:
        log.warning("Intent classify error: %s", e)
        intent = "general"

    # Terminal logs for debugging
    log.info("[IntentClassifier] User: %s", user_text)
    log.info("[IntentClassifier] Intent: %s", intent)

    # IMPORTANT: return in the same envelope shape your httpPostJSON callers expect
    return jok({"intent": intent})


# =========================
# Chat: /echo (+ streaming)
# =========================
@app.post("/echo")
def echo():
    data = request.get_json(force=True, silent=True) or {}
    user_input = (data.get("query") or "").strip()
    if not user_input:
        return jerror("Empty input", 400)

    _ = verify_google_token_if_enabled()

    try:
        if not client:
            return jok({"response": f"(offline) You said: {user_input}"})
        chat = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You're HushhVoice — a smart, useful, and consent-first AI assistant."},
                {"role": "user", "content": user_input},
            ],
            temperature=0.6,
            max_tokens=300,
        )
        return jok({"response": chat.choices[0].message.content.strip()})
    except Exception as e:
        log.exception("Echo error")
        return jerror(str(e), 500)


@app.post("/echo/stream")
def echo_stream():
    data = request.get_json(force=True, silent=True) or {}
    user_input = (data.get("query") or "").strip()
    if not user_input:
        return jerror("Empty input", 400)

    _ = verify_google_token_if_enabled()

    if not client:
        def gen_offline():
            yield "data: " + json.dumps({"delta": "(offline) "}) + "\n\n"
            time.sleep(0.2)
            yield "data: " + json.dumps({"delta": f"You said: {user_input}"}) + "\n\n"
            yield "event: done\ndata: {}\n\n"
        return Response(gen_offline(), mimetype="text/event-stream")

    def generate():
        try:
            with client.chat.completions.with_streaming_response.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You're HushhVoice — concise and helpful."},
                    {"role": "user", "content": user_input},
                ],
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


@app.post("/mailgpt/answer")
def mailgpt_answer():
    """
    One-shot: fetch last N emails and answer a natural-language question about them.
    Request body:
      {
        access_token?: string,          # or header X-Google-Access-Token
        query: string,                  # user question e.g. "Do I have any important mail from professors?"
        max_results?: number (default 20)
      }
    Response: { answer: str, emails_used: int, relevant_indices: [int], emails_preview: [...] }
    """
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jerror("Missing 'query' in request body.", 400)

    access_token = get_access_token_from_request(data)
    if not access_token:
        return jerror("Missing Gmail access token. Pass 'X-Google-Access-Token' header or 'access_token' in JSON.", 401, "unauthorized")

    max_results = int(data.get("max_results") or 20)
    try:
        emails = fetch_recent_emails(access_token, max_results=max_results) or []
    except Exception as e:
        log.exception("gmail fetch in /mailgpt/answer failed")
        return jerror(f"Gmail fetch failed: {e}", 500)

    if not client:
        # offline/dev fallback
        preview = trim_email_fields(emails)[:5]
        return jok({
            "answer": f"(offline) You asked: {query}. I fetched {len(emails)} emails.",
            "emails_used": len(emails),
            "relevant_indices": [],
            "emails_preview": preview
        })

    # Build constrained email context for the model
    emails_trimmed = trim_email_fields(emails)
    context = build_email_context(emails_trimmed, limit=max_results)

    system_prompt = (
        "You are an personal inbox analyst. "
        "You must answer ONLY using the provided emails and your own general knowledge"
        "Summarize clearly, highlight urgent or important items."
        "If unsure, say so. Keep the answer tight."
    )

    user_prompt = (
        f"User Query: {query}\n\n"
        f"Recent Emails (most recent first):\n"
        f"{context}\n\n"
        "Return a helpful answer in plain text. At the end, include a line: "
    )

    try:
        chat = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=400,
        )
        answer = chat.choices[0].message.content.strip()

        # quick parse of "Relevant: [..]" to extract indices if present
        import re
        rel = re.findall(r"Relevant:\s*\[([0-9,\s]+)\]", answer)
        relevant_indices: List[int] = []
        if rel:
            try:
                relevant_indices = [int(x.strip()) for x in rel[0].split(",") if x.strip().isdigit()]
            except Exception:
                relevant_indices = []

        return jok({
            "answer": answer,
            "emails_used": len(emails_trimmed),
            "relevant_indices": relevant_indices,
            "emails_preview": emails_trimmed[:min(5, len(emails_trimmed))],  # tiny preview for UI
        })
    except Exception as e:
        log.exception("mailgpt_answer error")
        return jerror(str(e), 500)


@app.post("/mailgpt/reply")
def mailgpt_reply():
    """
    Draft (and optionally send) a reply based on recent emails + instruction.
    Request body:
      {
        access_token?: string,
        instruction: string,
        max_results?: number (default 20),
        send?: bool (default false)
      }
    Response: { drafted: {to_email, subject, body}, sent?: bool }
    """
    data = request.get_json(force=True, silent=True) or {}
    instruction = (data.get("instruction") or "").strip()
    if not instruction:
        return jerror("Missing 'instruction' in request body.", 400)

    access_token = get_access_token_from_request(data)
    if not access_token:
        return jerror("Missing Gmail access token.", 401, "unauthorized")

    max_results = int(data.get("max_results") or 20)
    should_send = bool(data.get("send", False))

    try:
        inbox = fetch_recent_emails(access_token, max_results=max_results) or []
    except Exception as e:
        log.exception("gmail fetch in /mailgpt/reply failed")
        return jerror(f"Gmail fetch failed: {e}", 500)

    if not client:
        return jok({"drafted": {"to_email": "", "subject": "(offline)", "body": ""}, "sent": False})

    user_name = request.headers.get("X-User-Name") or "Best regards,"
    drafted = generate_reply_from_inbox(inbox, instruction, user_name=user_name)
    if not drafted:
        return jerror("Could not generate a reply.", 500, "draft_failed")

    # Optionally send
    sent = False
    if should_send:
        to_email = drafted["to_email"]
        subject = drafted["subject"]
        body = drafted["body"]
        if not to_email or not subject or not body:
            return jerror("Draft missing fields. Not sending.", 400, "invalid_draft")
        try:
            sent = send_email(access_token, to_email, subject, body)
        except Exception as e:
            log.exception("send_email failed")
            return jerror(f"Send failed: {e}", 500, "send_failed")

    return jok({"drafted": drafted, "sent": sent})



@app.post("/calendar/answer")
def calendar_answer():
    """
    Summarize or answer questions about the user's calendar across ALL calendars.
    Body:
      {
        query: string,
        time_min?: ISO  (default: now-14d)
        time_max?: ISO  (default: now+60d)
        max_results?: number (default 100),
        calendar_id?: string | null  # optional: force a single calendar
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
    force_cal_id = (data.get("calendar_id") or "").strip() or None

    # timezone-aware UTC (avoids DeprecationWarning)
    now = dt.datetime.now(dt.timezone.utc)
    time_min = (data.get("time_min") or _iso(now - dt.timedelta(days=14)))
    time_max = (data.get("time_max") or _iso(now + dt.timedelta(days=60)))

    try:
        # Helper to page through events for one calendar
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

        # Determine which calendars to search
        calendars = []
        if force_cal_id:
            calendars = [{"id": force_cal_id, "summary": force_cal_id}]
        else:
            cl = _google_get(access_token, "/users/me/calendarList", {"minAccessRole": "reader"})
            calendars = cl.get("items", [])
            if not calendars:
                log.info("[CalendarAnswer] No calendars visible for this account.")
                return jok({"answer": "I can’t see any calendars on this account.", "events_used": 0})

        log.info("[CalendarAnswer] Checking %d calendars in range %s to %s", len(calendars), time_min, time_max)

        # Aggregate events across calendars
        all_events = []
        for c in calendars:
            cal_id = c.get("id")
            cal_name = c.get("summary") or cal_id
            try:
                events = list_events_for_calendar(cal_id, time_min, time_max, max_results)
                if events:
                    log.info("[CalendarAnswer] %s -> %d events", cal_name, len(events))
                    # Annotate which calendar they’re from for later context
                    for e in events:
                        e["_calendar"] = cal_name
                    all_events.extend(events)
                else:
                    log.info("[CalendarAnswer] %s -> 0 events", cal_name)
            except Exception as e:
                log.warning("[CalendarAnswer] Failed to list events for %s: %s", cal_name, e)

        # Fallback: widen the window if nothing found
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

        # Build compact context for the model
        def fmt_evt(evt):
            start = (evt.get("start", {}).get("dateTime")
                     or evt.get("start", {}).get("date")
                     or "")
            end = (evt.get("end", {}).get("dateTime")
                   or evt.get("end", {}).get("date")
                   or "")
            where = evt.get("location") or ""
            attendees = ", ".join([a.get("email","") for a in evt.get("attendees", []) if a.get("email")])
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
            return jok({"answer": f"(offline) You asked: {question}. Fetched {len(all_events)} events.", "events_used": len(all_events)})

        system_prompt = (
            "You are CalendarGPT. Given a user question and a set of events from one or more calendars, "
            "answer clearly and helpfully. If the answer is uncertain, say so. Keep it crisp."
        )
        user_prompt = f"User Question:\n{question}\n\nEvents:\n{context}"

        chat = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=500,
        )
        answer = (chat.choices[0].message.content or "").strip()
        log.info("[CalendarAnswer] Calendars=%d EventsUsed=%d", len(calendars), len(all_events))
        return jok({"answer": answer, "events_used": len(all_events)})

    except Exception as e:
        log.exception("calendar_answer failed")
        return jerror(str(e), 500)




@app.post("/calendar/plan")
def calendar_plan():
    """
    Draft (and optionally create) a calendar event from natural language.
    Body:
      {
        instruction: string,
        confirm?: bool (default false),
        default_duration_minutes?: number (default 30),
        event?: {summary, start, end, timezone, attendees[], location, description, conference?: bool},
        send_updates?: "all"|"externalOnly"|"none"
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

    if not client and not confirm:
        # offline preview fallback
        return jok({
            "event": {
                "summary": instruction.slice(0, 60) if hasattr(instruction, "slice") else instruction[:60],
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
        if not confirm:
            # Preview with LLM: parse to event JSON
            system_prompt = (
                "You are CalendarGPT. Parse a natural language instruction into a calendar event JSON.\n"
                "Output STRICTLY valid JSON with keys:\n"
                "{\n"
                '  "summary": "string",                // title\n'
                '  "start": "YYYY-MM-DDTHH:MM",        // local datetime (no seconds)\n'
                '  "end": "YYYY-MM-DDTHH:MM",\n'
                '  "timezone": "IANA string",          // e.g., America/Los_Angeles\n'
                '  "attendees": ["email1", "email2"],\n'
                '  "location": "string",\n'
                '  "description": "string",\n'
                '  "conference": true|false            // request video link\n'
                "}\n"
                f"If the user doesn't specify an end time, default duration is {default_dur} minutes.\n"
                "If timezone is missing, infer from context conservatively or leave blank.\n"
            )
            user_prompt = (
                f"Instruction:\n{instruction}\n\n"
                "Return only JSON. No prose, no backticks."
            )

            chat = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_prompt}],
                temperature=0.4,
                max_tokens=500,
            )
            import json as _json
            obj = _json.loads((chat.choices[0].message.content or "").strip())
            # minimal normalization
            ev = {
                "summary": obj.get("summary") or "(No title)",
                "start": obj.get("start") or "",
                "end": obj.get("end") or "",
                "timezone": obj.get("timezone") or "",
                "attendees": [a for a in (obj.get("attendees") or []) if isinstance(a, str) and "@" in a],
                "location": obj.get("location") or "",
                "description": obj.get("description") or "",
                "conference": bool(obj.get("conference", False)),
            }
            # human summary
            hs = (
                f"Title: {ev['summary']}\n"
                f"When: {ev['start']} → {ev['end']}" + (f" ({ev['timezone']})" if ev['timezone'] else "") + "\n"
                + (f"Where: {ev['location']}\n" if ev['location'] else "")
                + (f"Attendees: {', '.join(ev['attendees'])}\n" if ev['attendees'] else "")
                + (f"Notes: {ev['description']}\n" if ev['description'] else "")
                + (f"Video: requested\n" if ev['conference'] else "")
            )
            return jok({"event": ev, "human_summary": hs})

        # confirm == True → create the event
        # Use event from client if provided, else (re)parse
        ev = data.get("event")
        if not ev:
            # (re)parse same as preview for safety
            if not client:
                return jerror("Cannot build event without model.", 500)
            system_prompt = (
                "You are CalendarGPT. Parse a natural language instruction into a calendar event JSON."
            )
            user_prompt = instruction
            chat = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_prompt}],
                temperature=0.2,
                max_tokens=300,
            )
            import json as _json
            ev = _json.loads((chat.choices[0].message.content or "").strip())

        # Build Google Calendar event resource
        # Expecting local datetimes; send as dateTime + (optional) timeZone
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

        # Video conference (Google Meet)
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

        created = _google_post(access_token, "/calendars/primary/events?conferenceDataVersion=1", g_event)
        return jok({"id": created.get("id"), "htmlLink": created.get("htmlLink"), "selfLink": created.get("selfLink")})

    except Exception as e:
        log.exception("calendar_plan failed")
        return jerror(str(e), 500)










# =========================
# Text-to-Speech Endpoint
# =========================
@app.post("/tts")
@cross_origin()
def tts():
    if not client:
        return jerror("OpenAI client not configured", 500, "no_client")

    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = (data.get("voice") or "alloy").strip()

    if not text:
        return jerror("Missing 'text' in request body", 400)

    try:
        # Generate entire MP3 in memory (non-streaming)
        result = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text
        )
        audio_bytes = result.read()  # get full MP3 bytes
        return Response(audio_bytes, mimetype="audio/mpeg")
    except Exception as e:
        log.exception("TTS generation error")
        return jerror(f"TTS generation failed: {e}", 500)


# =========================
# Run
# =========================
if __name__ == "__main__":
    app.run(port=PORT, debug=DEBUG, threaded=True)
