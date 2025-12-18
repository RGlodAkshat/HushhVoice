from __future__ import annotations

import os
import sys
import json
import time
import uuid
import logging
import datetime as dt
from typing import Dict, Any, List, Tuple, Optional

import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS, cross_origin
from dotenv import load_dotenv
from openai import OpenAI

# -------------------------------------------------------------------
# Path setup so we can import from backend/agents/*
# -------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))     # api/
ROOT_DIR = os.path.dirname(BASE_DIR)                      # project root
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Gmail helpers
from agents.email_assistant.gmail_fetcher import fetch_recent_emails, send_email
from agents.email_assistant.reply_helper import generate_reply_from_inbox
from agents.email_assistant.helper_functions import build_email_context, trim_email_fields

# =========================
# Config & Initialization
# =========================
load_dotenv()

APP_NAME = os.getenv("APP_NAME", "HushhVoice API")
APP_VERSION = os.getenv("APP_VERSION", "0.5.0")
PORT = int(os.getenv("PORT", "5050"))
DEBUG = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# On serverless platforms, code dir is read-only. Use /tmp for writes.
DEFAULT_MEMORY = "/tmp/hushh_memory.json"
MEMORY_PATH = os.getenv("MEMORY_PATH", DEFAULT_MEMORY)
try:
    mem_dir = os.path.dirname(MEMORY_PATH) or "/tmp"
    os.makedirs(mem_dir, exist_ok=True)
except Exception:
    # Ignore dir creation errors; we'll no-op writes later if needed.
    pass

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "hushh_secret_🔥")
CORS(app, supports_credentials=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hushhvoice")

client: Optional[OpenAI] = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)

# === Optional: Google ID token verification (independent from Gmail access token) ===
VERIFY_GOOGLE_TOKEN = os.getenv("VERIFY_GOOGLE_TOKEN", "false").lower() in ("1", "true", "yes")
if VERIFY_GOOGLE_TOKEN:
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
    except Exception:
        VERIFY_GOOGLE_TOKEN = False  # graceful fallback

GOOGLE_CAL_BASE = "https://www.googleapis.com/calendar/v3"

# =========================
# Google helper calls (Calendar)
# =========================
def _google_get(access_token: str, path: str, params: dict):
    url = f"{GOOGLE_CAL_BASE}{path}"
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
        timeout=20,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Google GET {path} -> {r.status_code} {r.text}")
    return r.json()


def _google_post(access_token: str, path: str, json_body: dict):
    url = f"{GOOGLE_CAL_BASE}{path}"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=json_body,
        timeout=20,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Google POST {path} -> {r.status_code} {r.text}")
    return r.json()


def _iso(dt_obj: dt.datetime) -> str:
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
    return dt_obj.isoformat().replace("+00:00", "Z")

def _normalize_event_datetime(dt_str: str, tz: Optional[str] = None) -> str:
    """
    Normalize a datetime string coming from the LLM into a format
    that Google Calendar will accept as 'dateTime'.

    Rules:
      - If empty, raise.
      - If format is 'YYYY-MM-DDTHH:MM', append ':00'.
      - If it already has 'Z', '+' or '-' after the date, keep as-is.
      - If it has no explicit offset, that's fine; we'll pass a separate
        'timeZone' field in the event.
    """
    if not dt_str:
        raise ValueError("Empty datetime string")

    dt_str = dt_str.strip()

    # If we have a simple local datetime without seconds like '2025-12-06T10:30'
    if "T" in dt_str:
        date_part, time_part = dt_str.split("T", 1)
        # 'HH:MM' is length 5; add ':SS'
        if len(time_part) == 5:
            dt_str = f"{date_part}T{time_part}:00"

    # Look at everything after the date portion
    tail = dt_str[10:]
    # If there's already a Z or an explicit offset, keep it as-is
    if any(c in tail for c in ("Z", "+", "-")):
        return dt_str

    # No explicit offset: we rely on the separate 'timeZone' field.
    return dt_str

# =========================
# JSON helpers
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


# =========================
# Auth helpers
# =========================
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
    Gmail/Calendar require an OAuth access token with appropriate scopes.
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
# OpenAI message assembly (short-term memory support)
# =========================
DEFAULT_SYSTEM = (
    "You are HushhVoice — a private, consent-first AI copilot. "
    "Use recent conversation history to resolve pronouns and ambiguity. "
    "Be concise, helpful, and ask for clarification only when truly needed."
)


def _normalize_message_role(m: dict) -> dict:
    role = m.get("role", "user")
    if role not in ("system", "user", "assistant"):
        role = "user"
    return {"role": role, "content": str(m.get("content", "")).strip()}


def _coerce_messages(messages: Any) -> List[Dict[str, str]]:
    """Coerce inbound messages array from the client into OpenAI chat format."""
    if not isinstance(messages, list):
        return []
    out: List[Dict[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        nm = _normalize_message_role(m)
        if nm["content"]:
            out.append(nm)
    return out


def _ensure_system_first(
    messages: List[Dict[str, str]],
    system_fallback: str = DEFAULT_SYSTEM,
) -> List[Dict[str, str]]:
    """Make sure there's a system prompt at the top."""
    if not messages:
        return [{"role": "system", "content": system_fallback}]
    if messages[0]["role"] != "system":
        return [{"role": "system", "content": system_fallback}] + messages
    # If there is a system but it's empty, replace it
    if not messages[0]["content"].strip():
        messages[0]["content"] = system_fallback
    return messages


def _append_task_block(
    messages: List[Dict[str, str]],
    block: str,
    as_user: bool = True,
) -> List[Dict[str, str]]:
    """Append a task-specific instruction/content block."""
    role = "user" if as_user else "assistant"
    if block and block.strip():
        messages.append({"role": role, "content": block.strip()})
    return messages


def _chat_complete(
    messages: List[Dict[str, str]],
    temperature: float = 0.6,
    max_tokens: int = 500,
) -> Dict[str, Any]:
    """Wrapper to call OpenAI chat with safety and offline fallback."""
    if not client:
        # Dev/offline fallback to show structure still works end-to-end
        joined = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-4:]])
        return {"offline": True, "content": f"(offline) {joined[-400:]}"}
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return {"offline": False, "content": (resp.choices[0].message.content or "").strip()}


# =========================
# Shared helpers for Siri + Web
# =========================
def classify_intent_text(user_text: str) -> str:
    """
    Classify a natural language query into one of:
      read_email, send_email, schedule_event, calendar_answer, health, general
    Uses the same responses+tools pattern as /intent/classify.
    """
    text = (user_text or "").strip()
    if not text:
        return "general"

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
                            "general",
                        ],
                    }
                },
                "required": ["intent"],
                "additionalProperties": False,
            },
            "strict": True,
        }]

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict intent classifier for a personal AI assistant. "
                        "Classify user queries into exactly one of: "
                        "read_email, send_email, schedule_event, calendar_answer, health, general."
                    ),
                },
                {"role": "user", "content": text},
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
        log.warning("Intent classify error (helper): %s", e)
        intent = "general"

    return intent


def answer_from_mail(
    access_token: str,
    query: str,
    max_results: int = 20,
    incoming_messages: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Shared email QA core:
      - fetch recent emails via Gmail
      - trim fields
      - build LLM prompt
      - call OpenAI
    Returns a dict like /mailgpt/answer would return.
    Raises RuntimeError on hard failure.
    """
    if not access_token:
        raise RuntimeError("Missing Gmail access token")

    # 1) Fetch emails from Gmail
    try:
        emails = fetch_recent_emails(access_token, max_results=max_results) or []
    except Exception as e:
        log.exception("gmail fetch in answer_from_mail failed")
        raise RuntimeError(f"Gmail fetch failed: {e}") from e

    emails_trimmed = trim_email_fields(emails)
    context = build_email_context(emails_trimmed, limit=max_results)

    # 2) Offline / no-OpenAI fallback
    if not client:
        preview = emails_trimmed[:5]
        return {
            "answer": f"(offline) You asked: {query}. I fetched {len(emails)} emails.",
            "emails_used": len(emails_trimmed),
            "relevant_indices": [],
            "emails_preview": preview,
        }

    # 3) Build messages with memory + task block
    base_messages = _coerce_messages(incoming_messages) if incoming_messages else []
    messages = _ensure_system_first(base_messages, DEFAULT_SYSTEM)

    system_prompt = (
        "You are a personal inbox analyst. "
        "Use ONLY the provided email context and general knowledge to answer. "
        "Summarize clearly, highlight urgent/important items, and say if unsure."
    )
    messages.append({"role": "system", "content": system_prompt})

    user_block = (
        f"User Query:\n{query}\n\n"
        f"Recent Emails (most recent first):\n{context}\n\n"
        "Return a helpful answer in plain text. "
        "If you cite specific emails, reference key details."
    )
    messages = _append_task_block(messages, user_block, as_user=True)

    # 4) Call OpenAI
    out = _chat_complete(messages, temperature=0.4, max_tokens=1000)
    answer = out["content"]

    # 5) Optional parse of "Relevant: [..]" if present
    import re
    rel = re.findall(r"Relevant:\s*\[([0-9,\s]+)\]", answer or "")
    relevant_indices: List[int] = []
    if rel:
        try:
            relevant_indices = [
                int(x.strip()) for x in rel[0].split(",") if x.strip().isdigit()
            ]
        except Exception:
            relevant_indices = []

    return {
        "answer": answer,
        "emails_used": len(emails_trimmed),
        "relevant_indices": relevant_indices,
        "emails_preview": emails_trimmed[: min(5, len(emails_trimmed))],
    }


def draft_reply_from_mail(
    access_token: str,
    instruction: str,
    user_name: str,
    max_results: int = 20,
    incoming_messages: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Shared email reply drafting core:
      - fetch recent inbox
      - use generate_reply_from_inbox(...)
    Returns dict {to_email, subject, body}.
    """
    if not access_token:
        raise RuntimeError("Missing Gmail access token")
    if not instruction.strip():
        raise RuntimeError("Missing instruction for reply")

    try:
        inbox = fetch_recent_emails(access_token, max_results=max_results) or []
    except Exception as e:
        log.exception("gmail fetch in draft_reply_from_mail failed")
        raise RuntimeError(f"Gmail fetch failed: {e}") from e

    drafted = generate_reply_from_inbox(inbox, instruction, user_name=user_name)
    if not drafted:
        raise RuntimeError("Could not generate a reply draft")

    return drafted


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
    return jok(
        {
            "name": APP_NAME,
            "version": APP_VERSION,
            "openai": bool(client),
            "verify_google_token": VERIFY_GOOGLE_TOKEN,
        }
    )


@app.get("/version")
def version():
    return jok({"name": APP_NAME, "version": APP_VERSION})


# =========================
# Intent Classifier (web)
# =========================
@app.post("/intent/classify")
def intent_classify_route():
    data = request.get_json(force=True, silent=True) or {}
    user_text = (data.get("query") or "").strip()
    intent = classify_intent_text(user_text)
    log.info("[IntentClassifier] User: %s", user_text)
    log.info("[IntentClassifier] Intent: %s", intent)
    return jok({"intent": intent})


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


# =========================
# Siri: /siri/ask (iOS + Shortcuts)
# =========================
@app.post("/siri/ask")
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

    user_email = request.headers.get("X-User-Email") or "siri@local"

    # Base messages for general chat
    messages = [
        {
            "role": "system",
            "content": (
                "You are HushhVoice — Siri channel. "
                "Respond briefly for speech. If the user asked about email or calendar "
                "but access is missing or broken, say so plainly and stop."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        # 3) Classify intent
        intent = classify_intent_text(prompt)
        log.info("[Siri] user=%s intent=%s", user_email, intent)

        # 4) If mail/calendar/health intents require Google and we don't have a token
        if intent in ("read_email", "send_email", "calendar_answer", "schedule_event") and not gtoken:
            msg = "I need Google access to do that. Open HushhVoice to connect Gmail and Calendar."
            return jok({"speech": msg, "display": msg})

        # 5) Intent-specific handling

        # --- Email summarize ---
        if intent == "read_email":
            try:
                result = answer_from_mail(
                    access_token=gtoken,
                    query=prompt,
                    max_results=20,
                    incoming_messages=None,
                )
                speech = result.get("answer") or "No answer."
                return jok({"speech": speech[:350], "display": speech})
            except Exception as e:
                log.exception("Siri read_email failed: %s", e)
                msg = "I hit an error reading your inbox. Please try again later."
                return jok({"speech": msg, "display": msg})

        # --- Email reply (draft + send) ---
        if intent == "send_email":
            try:
                user_name = request.headers.get("X-User-Name") or "Best regards,"
                # Optional flag from client; defaults to True
                send_now = bool(data.get("send_now", True))

                drafted = draft_reply_from_mail(
                    access_token=gtoken,
                    instruction=prompt,
                    user_name=user_name,
                    max_results=20,
                    incoming_messages=None,
                )
                to_email = drafted.get("to_email") or "(unknown)"
                subject = drafted.get("subject") or "(no subject)"
                body = drafted.get("body") or ""

                sent = False
                if send_now and to_email != "(unknown)":
                    try:
                        sent = send_email(gtoken, to_email, subject, body)
                    except Exception as e:
                        log.exception("Siri send_email send failed: %s", e)
                        sent = False

                if sent:
                    speech = f"Sent your email to {to_email} with subject: {subject}."
                    display = (
                        f"✅ **Email sent**\n\n"
                        f"- **To:** {to_email}\n"
                        f"- **Subject:** {subject}\n\n"
                        f"```text\n{body}\n```"
                    )
                else:
                    speech = f"Drafted an email to {to_email} with subject: {subject}."
                    display = (
                        f"**Draft preview**\n\n"
                        f"- **To:** {to_email}\n"
                        f"- **Subject:** {subject}\n\n"
                        f"```text\n{body}\n```"
                    )

                return jok({"speech": speech[:350], "display": display, "sent": sent})
            except Exception as e:
                log.exception("Siri send_email failed: %s", e)
                msg = "I couldn't send that email right now. Please try again in the app."
                return jok({"speech": msg, "display": msg})

        # --- Calendar summarize ---
        if intent == "calendar_answer":
            try:
                result = calendar_answer_core(
                    access_token=gtoken,
                    question=prompt,
                    time_min=None,
                    time_max=None,
                    max_results=50,
                    incoming_messages=None,
                )
                speech = result.get("answer") or "No events found."
                return jok({"speech": speech[:350], "display": speech})
            except Exception as e:
                log.exception("Siri calendar_answer failed: %s", e)
                msg = "I hit an error reading your calendar. Try again in a bit."
                return jok({"speech": msg, "display": msg})

                # --- Calendar scheduling (draft + create) ---
        if intent == "schedule_event":
            try:
                user_name = request.headers.get("X-User-Name") or ""

                # Optional timezone hint from iOS client
                req_tz = (data.get("timezone") or "").strip() or None
                default_tz = os.getenv("DEFAULT_TZ", "UTC")

                draft = calendar_plan_core(
                    access_token=gtoken,
                    instruction=prompt,
                    confirm=False,
                    default_dur=30,
                    user_name=user_name,
                    incoming_messages=None,
                )
                ev = draft.get("event", {}) or {}
                hs = draft.get("human_summary", "")

                if not ev:
                    msg = "I couldn’t draft that event."
                    return jok({"speech": msg, "display": msg})

                start_raw = ev.get("start") or ""
                end_raw = ev.get("end") or ""

                # 🔑 Always have a timezone: event → request → env → UTC
                tz = (
                    (ev.get("timezone") or "").strip()
                    or req_tz
                    or default_tz
                )

                if not start_raw or not end_raw:
                    raise RuntimeError(f"Parsed event missing start/end: {ev}")

                start_dt = _normalize_event_datetime(start_raw, tz)
                end_dt = _normalize_event_datetime(end_raw, tz)

                start_obj = {
                    "dateTime": start_dt,
                    "timeZone": tz,
                }
                end_obj = {
                    "dateTime": end_dt,
                    "timeZone": tz,
                }

                g_event: dict = {
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

                created = _google_post(
                    gtoken,
                    "/calendars/primary/events?conferenceDataVersion=1",
                    g_event,
                )

                speech = f"Scheduled {ev.get('summary', '(no title)')} at {start_dt}."
                display = hs or speech

                return jok({
                    "speech": speech[:300],
                    "display": display,
                    "event_id": created.get("id"),
                    "event_link": created.get("htmlLink"),
                })
            except Exception as e:
                log.exception("Siri schedule_event failed: %s", e)
                # Dev-friendly: keep speech user-facing, show error in display for debugging
                speech = "I hit an error scheduling that event. Please try again later."
                display = f"{speech}\n\n[debug] {e}"
                return jok({"speech": speech, "display": display})


        # --- Health placeholder ---
        if intent == "health":
            msg = (
                "Health integration is still in preview. "
                "Use the HushhVoice app or web to pair a supported device."
            )
            return jok({"speech": msg, "display": msg})

        # --- General chat fallback ---
        out = _chat_complete(messages, temperature=0.5, max_tokens=240)
        text = out["content"] or "Sorry, I didn’t catch that."
        return jok({"speech": text[:350], "display": text})

    except Exception as e:
        log.exception("Siri ask failed")
        msg = "I ran into an error answering that. Please try again in a bit."
        return jok({"speech": msg, "display": msg})


# =========================
# Mail Q&A (web)
# =========================
@app.post("/mailgpt/answer")
def mailgpt_answer():
    """
    One-shot: fetch last N emails and answer a natural-language question about them.
    Request body:
      {
        access_token?: string,          # or header X-Google-Access-Token
        query: string,
        max_results?: number (default 20),
        messages?: [ {role, content}, ... ]
      }
    Response:
      {
        answer: str,
        emails_used: int,
        relevant_indices: [int],
        emails_preview: [...]
      }
    """
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jerror("Missing 'query' in request body.", 400)

    access_token = get_access_token_from_request(data)
    if not access_token:
        return jerror(
            "Missing Gmail access token. Pass 'X-Google-Access-Token' header or 'access_token' in JSON.",
            401,
            "unauthorized",
        )

    max_results = int(data.get("max_results") or 20)
    incoming_messages = data.get("messages") or []

    try:
        result = answer_from_mail(
            access_token=access_token,
            query=query,
            max_results=max_results,
            incoming_messages=incoming_messages,
        )
        return jok(result)
    except Exception as e:
        log.exception("mailgpt_answer error")
        # Friendly, non-fatal fallback so web UI stays usable
        return jok({
            "answer": (
                "I couldn’t access your Gmail right now. "
                "Your token may be expired or misconfigured. Try reconnecting and asking again."
            ),
            "emails_used": 0,
            "relevant_indices": [],
            "emails_preview": [],
        })


# =========================
# Mail Reply (web)
# =========================
@app.post("/mailgpt/reply")
def mailgpt_reply():
    """
    Draft (and optionally send) a reply based on recent emails + instruction.
    Request body:
      {
        access_token?: string,
        instruction: string,
        max_results?: number (default 20),
        send?: bool (default false),
        messages?: [ {role, content}, ... ]
      }
    Response:
      { drafted: {to_email, subject, body}, sent?: bool }
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

    # Build prompt with memory window + task block (we keep your helper-based drafting for real content)
    incoming_messages = _coerce_messages(data.get("messages"))
    messages = _ensure_system_first(incoming_messages, DEFAULT_SYSTEM)

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


# =========================
# Calendar Answer (web)
# =========================
@app.post("/calendar/answer")
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
        result = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
        )
        audio_bytes = result.read()  # get full MP3 bytes
        return Response(audio_bytes, mimetype="audio/mpeg")
    except Exception as e:
        log.exception("TTS generation error")
        return jerror(f"TTS generation failed: {e}", 500)

# =========================
# /onboarding/agent (PUBLIC TEST)
# Human, talkative onboarding + structured extraction (json_schema strict)
# =========================

HUSHHVOICE_URL_SUPABASE = os.getenv("HUSHHVOICE_URL_SUPABASE", "").rstrip("/")
HUSHHVOICE_ANON_KEY_SUPABASE = os.getenv("HUSHHVOICE_ANON_KEY_SUPABASE", "").strip()
ONBOARDING_TABLE_HUSHHVOICE = "onboarding_data_public_test"

# "Ready" means: enough to prefill the website flow without sensitive bank numbers / SSN / DOB.
MIN_READY_FIELDS_HUSHHVOICE = [
    "investment_tier",          # standard | premium | ultra
    "account_type",             # general | retirement
    "account_structure",        # individual | other
    "legal_first_name",
    "legal_last_name",
    "city",
    "state",
    "zip_code",
    "initial_investment_amount",
    "phone_number",
    "residence_country",
    "citizenship_country",
    "residency_confirmed",
    "referral_source",
]

# -------------------------
# Supabase helpers
# -------------------------
def _sb_headers_hushhvoice():
    if not HUSHHVOICE_URL_SUPABASE or not HUSHHVOICE_ANON_KEY_SUPABASE:
        raise RuntimeError("Missing HUSHHVOICE_URL_SUPABASE or HUSHHVOICE_ANON_KEY_SUPABASE")
    return {
        "apikey": HUSHHVOICE_ANON_KEY_SUPABASE,
        "Authorization": f"Bearer {HUSHHVOICE_ANON_KEY_SUPABASE}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

def _sb_get_row_hushhvoice(client_user_id: str) -> dict:
    url = (
        f"{HUSHHVOICE_URL_SUPABASE}/rest/v1/{ONBOARDING_TABLE_HUSHHVOICE}"
        f"?client_user_id=eq.{client_user_id}&select=*"
    )
    r = requests.get(url, headers=_sb_headers_hushhvoice(), timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase GET failed: {r.status_code} {r.text}")
    rows = r.json() or []
    return rows[0] if rows else {}

def _sb_upsert_row_hushhvoice(client_user_id: str, patch: dict) -> dict:
    url = f"{HUSHHVOICE_URL_SUPABASE}/rest/v1/{ONBOARDING_TABLE_HUSHHVOICE}?on_conflict=client_user_id"
    payload = {"client_user_id": client_user_id, **(patch or {})}
    r = requests.post(url, headers=_sb_headers_hushhvoice(), json=payload, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase UPSERT failed: {r.status_code} {r.text}")
    rows = r.json() or []
    return rows[0] if rows else payload

def _missing_fields_hushhvoice(row: dict) -> list[str]:
    return [f for f in MIN_READY_FIELDS_HUSHHVOICE if row.get(f) in (None, "", [])]

def _clean_patch(patch_obj: dict) -> dict:
    patch = {}
    for k, v in (patch_obj or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        patch[k] = v

    # Normalize phone fields
    if "phone_country_code" in patch:
        s = str(patch["phone_country_code"]).strip()
        if s and not s.startswith("+"):
            s = "+" + s
        patch["phone_country_code"] = s[:6]

    if "phone_number" in patch:
        import re
        d = re.sub(r"\D", "", str(patch["phone_number"]))
        patch["phone_number"] = d[:15] if d else patch["phone_number"]

    # Normalize tier to lowercase bucket words if present
    if "investment_tier" in patch and isinstance(patch["investment_tier"], str):
        patch["investment_tier"] = patch["investment_tier"].strip().lower()

    return patch


# -------------------------
# LLM turn: extract + human response + next question
# -------------------------
def _openai_onboarding_turn_hushhvoice(
    user_text: str,
    current_row: dict,
    missing_fields: list[str],
    questions_asked: int,
) -> dict:
    if not client:
        # Offline fallback, still conversational
        if not missing_fields:
            return {
                "patch": {},
                "assistant_text": "Nice — that’s everything I needed. I’ll take you to HushhTech to finish up.",
                "should_redirect": True,
            }
        nice = missing_fields[0].replace("_", " ")
        return {
            "patch": {},
            "assistant_text": f"Got it. Quick one — what should I fill for your {nice}?",
            "should_redirect": False,
        }

    # --- Fields we can safely prefill (NO SSN/DOB/routing/account numbers) ---
    props = {
        # Basic identity + contact
        "legal_first_name": {"type": ["string", "null"]},
        "legal_last_name": {"type": ["string", "null"]},
        "phone_country_code": {"type": ["string", "null"]},
        "phone_number": {"type": ["string", "null"]},

        # Address / residency
        "address_line_1": {"type": ["string", "null"]},
        "address_line_2": {"type": ["string", "null"]},
        "city": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"]},
        "zip_code": {"type": ["string", "null"]},
        "address_country": {"type": ["string", "null"]},
        "citizenship_country": {"type": ["string", "null"]},
        "residence_country": {"type": ["string", "null"]},
        "residency_confirmed": {"type": ["boolean", "null"]},

        # Account choices
        "account_type": {"type": ["string", "null"], "enum": ["general", "retirement", None]},
        "account_structure": {"type": ["string", "null"], "enum": ["individual", "other", None]},
        "investment_tier": {"type": ["string", "null"], "enum": ["standard", "premium", "ultra", None]},

        # Investment
        "initial_investment_amount": {"type": ["number", "null"]},
        "recurring_investment_enabled": {"type": ["boolean", "null"]},
        "recurring_frequency": {"type": ["string", "null"], "enum": ["weekly","biweekly","monthly","bimonthly", None]},
        "recurring_amount": {"type": ["number", "null"]},
        "recurring_day_of_month": {"type": ["integer", "null"], "minimum": 1, "maximum": 31},

        # Fund A selection
        "selected_fund": {"type": ["string", "null"]},  # e.g. hushh_fund_a
        "fund_class_a_units": {"type": ["integer", "null"], "minimum": 0},
        "fund_class_b_units": {"type": ["integer", "null"], "minimum": 0},
        "fund_class_c_units": {"type": ["integer", "null"], "minimum": 0},
        "total_investment_amount": {"type": ["number", "null"]},

        # Light banking (allowed)
        "bank_name": {"type": ["string", "null"]},
        "bank_account_type": {"type": ["string", "null"], "enum": ["checking", "savings", None]},

        # Referral
        "referral_source": {"type": ["string", "null"], "enum": [
            "podcast",
            "social_media_influencer",
            "social_media_ad",
            "yahoo_finance",
            "ai_tool",
            "website_blog_article",
            "the_penny_hoarder",
            "family_or_friend",
            "tv_or_radio",
            "other",
            None
        ]},
        "referral_source_other": {"type": ["string", "null"]},

        # Optional context from your first 2 standard questions
        "net_worth": {"type": ["string", "null"]},
        "investment_goals": {"type": ["string", "null"]},
    }

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "patch": {
                "type": "object",
                "additionalProperties": False,
                "properties": props,
                "required": list(props.keys()),  # json_schema strict requirement
            },
            "assistant_text": {"type": "string"},
            "should_redirect": {"type": "boolean"},
        },
        "required": ["patch", "assistant_text", "should_redirect"],
    }

    # Keep saved context small
    saved_subset = {}
    for k in props.keys():
        v = current_row.get(k)
        if v not in (None, "", [], {}):
            saved_subset[k] = v

    # Website copy injected as "knowledge" the agent can paraphrase/explain
    website_context = {
        "tiers": {
            "standard": {"min": 1_000_000, "label": "Hushh Wealth Investment Account"},
            "premium": {"min": 5_000_000, "label": "Hushh Wealth Investment Account (Premium)"},
            "ultra": {"min": 25_000_000, "label": "Hushh Ultra High Net Worth Investment Account"},
        },
        "fund_a_classes": {
            "class_a": {"unit": 25_000_000, "tier": "ultra"},
            "class_b": {"unit": 5_000_000, "tier": "premium"},
            "class_c": {"unit": 1_000_000, "tier": "standard"},
        },
        "resident_rule": "We currently accept investments from residents of the United States only.",
        "do_not_collect": ["SSN", "DOB", "routing number", "account number", "account holder name"],
    }

    system_prompt = (
        "You are Agent Kai — a warm, talkative, human onboarding concierge for Hushh Fund A.\n"
        "You must produce ONE turn with 3 outputs: patch, assistant_text, should_redirect.\n\n"
        "Extraction rules (patch):\n"
        "- Extract ONLY what the user explicitly provided. Otherwise output null.\n"
        "- Never invent.\n"
        "- Convert money to numbers for numeric fields (e.g. '$1,000,000' -> 1000000).\n"
        "- Phone number: digits only if possible.\n"
        "- Never collect or ask for SSN, DOB, routing/account numbers, or account holder name.\n\n"
        "Conversation rules (assistant_text):\n"
        "- Sound like a real person. Start with a brief acknowledgement referencing what they said (1–2 short sentences).\n"
        "- If the next thing you ask is a concept, explain it simply BEFORE asking:\n"
        "  * investment_tier (standard/premium/ultra) with the minimums\n"
        "  * account_structure (individual vs other)\n"
        "  * Fund A classes (Class A/B/C) with unit minimums\n"
        "- Ask ONE question that can capture multiple missing fields at once.\n"
        "- Max 4 short sentences total. No bullets, no headings.\n"
    )

    user_payload = {
        "latest_user_message": user_text,
        "questions_asked": questions_asked,
        "missing_fields": missing_fields,
        "already_saved": saved_subset,
        "website_context": website_context,
    }

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.7,  # slightly higher -> more human tone
        max_tokens=320,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "onboarding_turn", "schema": schema, "strict": True},
        },
    )

    raw = (resp.choices[0].message.content or "").strip()
    obj = json.loads(raw)

    return {
        "patch": _clean_patch(obj.get("patch") or {}),
        "assistant_text": (obj.get("assistant_text") or "").strip(),
        "should_redirect": bool(obj.get("should_redirect", False)),
    }


@app.post("/onboarding/agent")
def onboarding_agent():
    data = request.get_json(force=True, silent=True) or {}

    client_user_id = (data.get("client_user_id") or "").strip()
    user_text = (data.get("user_text") or "").strip()
    questions_asked = int(data.get("questions_asked") or 1)

    if not client_user_id:
        return jerror("Missing client_user_id", 400)
    if not user_text:
        return jerror("Missing user_text", 400)

    try:
        current = _sb_get_row_hushhvoice(client_user_id) or {}
        missing_before = _missing_fields_hushhvoice(current)

        turn = _openai_onboarding_turn_hushhvoice(
            user_text=user_text,
            current_row=current,
            missing_fields=missing_before,
            questions_asked=questions_asked,
        )

        patch = turn["patch"]
        saved = _sb_upsert_row_hushhvoice(client_user_id, patch) if patch else (current or {"client_user_id": client_user_id})

        missing_after = _missing_fields_hushhvoice(saved)

        # Optional: enforce US residency gating (without being rude)
        # If user said they are NOT a US resident, don't redirect; keep clarifying.
        if saved.get("residence_country") and str(saved.get("residence_country")).strip().lower() not in ("united states", "usa", "us"):
            # keep going, ask to confirm residency
            if "residency_confirmed" not in missing_after and saved.get("residency_confirmed") is True:
                # still disallow redirect if not US
                pass

        should_redirect = bool(turn["should_redirect"]) or (not missing_after) or (questions_asked >= 12)

        # If not US resident, do NOT redirect even if other fields are complete
        if saved.get("residence_country") and str(saved.get("residence_country")).strip().lower() not in ("united states", "usa", "us"):
            should_redirect = False

        if should_redirect:
            _sb_upsert_row_hushhvoice(client_user_id, {
                "is_completed": True,
                "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            })

        assistant_text = (
            "Awesome — that’s enough for me to pre-fill everything cleanly. I’ll take you to HushhTech to review and submit."
            if should_redirect
            else (turn["assistant_text"] or "Got it — what should we fill next?")
        )

        return jok({
            "assistant_text": assistant_text,
            "updates_applied": patch,
            "missing_fields": missing_after,
            "next_action": "redirect" if should_redirect else "continue",
        })

    except Exception as e:
        return jerror(str(e), 500)


# run
# =========================
# Run
# =========================
if __name__ == "__main__":
    # Local dev only; Render will use gunicorn.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", PORT)), debug=DEBUG)



