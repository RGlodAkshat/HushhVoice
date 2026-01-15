from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from clients.google_client import _google_get, _google_post, _normalize_event_datetime, _iso
from clients.openai_client import client
from config import OPENAI_MODEL, log
from services.memory_service import search_memory, write_memory
from storage.profile_store import load_profile
from agents.email_assistant.gmail_fetcher import fetch_recent_emails, send_email
from agents.email_assistant.helper_functions import trim_email_fields
from utils.debug_events import debug_enabled, record_event


MAX_TOOL_STEPS = 6


@dataclass
class ToolContext:
    user_id: str
    google_token: Optional[str]
    user_email: Optional[str]
    locale: Optional[str]
    timezone: Optional[str]
    request_id: Optional[str]


_EMAIL_EXTRACT_RE = re.compile(r"<([^>]+)>")
_EMAIL_FIND_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_EMAIL_VALID_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(addr: str) -> str:
    raw = (addr or "").strip()
    if not raw:
        return ""
    match = _EMAIL_FIND_RE.search(raw)
    if match:
        raw = match.group(0)
    match = _EMAIL_EXTRACT_RE.search(raw)
    if match:
        raw = match.group(1)
    raw = raw.strip().strip(").,;:")
    if raw.endswith("."):
        raw = raw.rstrip(".")
    return raw if _EMAIL_VALID_RE.match(raw) else ""


def _clean_email_list(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    parts = [p.strip() for p in re.split(r"[;,]", raw) if p.strip()]
    cleaned = [e for e in (_clean_email(p) for p in parts) if e]
    return ", ".join(cleaned) if cleaned else None


def _tool_ok(data: Any) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def _tool_err(message: str, code: str = "tool_error") -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _require_google(ctx: ToolContext) -> Optional[Dict[str, Any]]:
    if not ctx.google_token:
        return _tool_err(
            "Missing Google access token. Ask the user to connect Gmail/Calendar.",
            "missing_google_token",
        )
    return None


def _gmail_search(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    missing = _require_google(ctx)
    if missing:
        return missing
    query = (args.get("query") or "").strip()
    max_results = int(args.get("max_results") or 10)
    try:
        emails = fetch_recent_emails(
            access_token=ctx.google_token,
            max_results=max_results,
            q=query or None,
            label_ids=None,
            include_snippet=True,
        )
        return _tool_ok({"emails": trim_email_fields(emails)})
    except Exception as e:
        log.exception("gmail_search failed")
        return _tool_err(str(e))


def _gmail_send(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    missing = _require_google(ctx)
    if missing:
        return missing
    raw_to = args.get("to") or args.get("to_email") or args.get("recipient") or ""
    if isinstance(raw_to, list):
        raw_to = ",".join([str(v) for v in raw_to])
    to_email = _clean_email(str(raw_to))
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "").strip()
    cc = _clean_email_list(str(args.get("cc") or "").strip()) or None
    bcc = _clean_email_list(str(args.get("bcc") or "").strip()) or None
    thread_id = (args.get("thread_id") or "").strip() or None
    if not to_email:
        log.warning("gmail_send invalid recipient raw=%s", args.get("to"))
        if debug_enabled():
            record_event(
                "gmail",
                "invalid recipient",
                data={"raw_to": args.get("to")},
                request_id=ctx.request_id,
                level="error",
            )
        return _tool_err("Invalid recipient email address. Please confirm and try again.", "invalid_email")
    if not subject or not body:
        return _tool_err("to, subject, and body are required", "invalid_arguments")
    sent = send_email(
        access_token=ctx.google_token,
        to_email=to_email,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        thread_id=thread_id,
    )
    if not sent:
        log.warning("gmail_send failed to=%s", to_email)
        if debug_enabled():
            record_event(
                "gmail",
                "send_email returned False",
                data={"to": to_email, "subject": subject},
                request_id=ctx.request_id,
                level="error",
            )
        return _tool_err("Gmail send failed. Verify the address and try again.", "send_failed")
    return _tool_ok({"sent": True, "to": to_email, "subject": subject})


def _calendar_list_events(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    missing = _require_google(ctx)
    if missing:
        return missing
    max_results = int(args.get("max_results") or 50)
    now = datetime.now(timezone.utc)
    time_min = args.get("time_min") or _iso(now - timedelta(days=14))
    time_max = args.get("time_max") or _iso(now + timedelta(days=60))
    try:
        resp = _google_get(
            ctx.google_token,
            "/calendars/primary/events",
            {
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": min(max_results, 250),
            },
        )
        items = resp.get("items", []) or []
        events = []
        for e in items:
            events.append({
                "id": e.get("id"),
                "summary": e.get("summary") or "(No title)",
                "start": (e.get("start", {}) or {}).get("dateTime") or (e.get("start", {}) or {}).get("date"),
                "end": (e.get("end", {}) or {}).get("dateTime") or (e.get("end", {}) or {}).get("date"),
                "location": e.get("location"),
                "attendees": [a.get("email") for a in (e.get("attendees") or []) if a.get("email")],
            })
        return _tool_ok({"events": events})
    except Exception as e:
        log.exception("calendar_list_events failed")
        return _tool_err(str(e))


def _calendar_find_availability(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    # Simple wrapper: return busy events in the window.
    return _calendar_list_events(args, ctx)


def _calendar_create_event(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    missing = _require_google(ctx)
    if missing:
        return missing
    summary = (args.get("summary") or "").strip() or "(No title)"
    start = (args.get("start") or "").strip()
    end = (args.get("end") or "").strip()
    tz = (args.get("timezone") or ctx.timezone or "UTC").strip()
    if not start or not end:
        return _tool_err("start and end are required", "invalid_arguments")

    try:
        start_dt = _normalize_event_datetime(start, tz)
        end_dt = _normalize_event_datetime(end, tz)
        start_obj = {"dateTime": start_dt, "timeZone": tz}
        end_obj = {"dateTime": end_dt, "timeZone": tz}

        g_event: Dict[str, Any] = {"summary": summary, "start": start_obj, "end": end_obj}
        if args.get("location"):
            g_event["location"] = args.get("location")
        if args.get("description"):
            g_event["description"] = args.get("description")
        attendees = args.get("attendees") or []
        if isinstance(attendees, list) and attendees:
            g_event["attendees"] = [{"email": a} for a in attendees if isinstance(a, str) and "@" in a]
        if bool(args.get("conference", False)):
            g_event["conferenceData"] = {
                "createRequest": {
                    "requestId": summary[:20],
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        created = _google_post(
            ctx.google_token,
            "/calendars/primary/events?conferenceDataVersion=1",
            g_event,
        )
        return _tool_ok({
            "id": created.get("id"),
            "htmlLink": created.get("htmlLink"),
            "summary": created.get("summary") or summary,
        })
    except Exception as e:
        log.exception("calendar_create_event failed")
        return _tool_err(str(e))


def _profile_get(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    user_id = (args.get("user_id") or ctx.user_id or "").strip()
    if not user_id:
        return _tool_err("Missing user_id", "invalid_arguments")
    row = load_profile(user_id)
    if not row:
        return _tool_ok({"exists": False, "profile": None})
    return _tool_ok({"exists": True, "profile": row})


def _memory_search(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    query = (args.get("query") or "").strip()
    limit = int(args.get("limit") or 5)
    if not query:
        return _tool_err("query is required", "invalid_arguments")
    results = search_memory(ctx.user_id, query=query, limit=limit)
    return _tool_ok({"results": results})


def _memory_write(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    content = (args.get("content") or "").strip()
    tags = args.get("tags") or []
    source = (args.get("source") or "siri").strip()
    if not content:
        return _tool_err("content is required", "invalid_arguments")
    entry = write_memory(ctx.user_id, content=content, tags=tags, source=source, sync=True)
    return _tool_ok({"memory": entry})


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[[Dict[str, Any], ToolContext], Dict[str, Any]]


TOOL_SPECS: Dict[str, ToolSpec] = {
    "gmail_search": ToolSpec(
        name="gmail_search",
        description="Search recent Gmail messages by query and return compact metadata.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query (e.g. from:xyz subject:hello)"},
                "max_results": {"type": "integer", "description": "Max emails to return", "default": 10},
            },
        },
        handler=_gmail_search,
    ),
    "gmail_send": ToolSpec(
        name="gmail_send",
        description="Send an email via Gmail API.",
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "cc": {"type": "string"},
                "bcc": {"type": "string"},
                "thread_id": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        handler=_gmail_send,
    ),
    "calendar_list_events": ToolSpec(
        name="calendar_list_events",
        description="List calendar events in a time window.",
        parameters={
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "ISO datetime"},
                "time_max": {"type": "string", "description": "ISO datetime"},
                "max_results": {"type": "integer", "default": 50},
            },
        },
        handler=_calendar_list_events,
    ),
    "calendar_find_availability": ToolSpec(
        name="calendar_find_availability",
        description="Return busy events for a window; model picks a free slot.",
        parameters={
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "ISO datetime"},
                "time_max": {"type": "string", "description": "ISO datetime"},
                "max_results": {"type": "integer", "default": 50},
            },
        },
        handler=_calendar_find_availability,
    ),
    "calendar_create_event": ToolSpec(
        name="calendar_create_event",
        description="Create a calendar event in the user's primary calendar.",
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start": {"type": "string", "description": "ISO datetime"},
                "end": {"type": "string", "description": "ISO datetime"},
                "timezone": {"type": "string", "description": "IANA timezone"},
                "attendees": {"type": "array", "items": {"type": "string"}},
                "location": {"type": "string"},
                "description": {"type": "string"},
                "conference": {"type": "boolean"},
            },
            "required": ["start", "end"],
        },
        handler=_calendar_create_event,
    ),
    "profile_get": ToolSpec(
        name="profile_get",
        description="Fetch a user's profile (name/phone/email).",
        parameters={
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
        },
        handler=_profile_get,
    ),
    "memory_search": ToolSpec(
        name="memory_search",
        description="Search long-term memory for relevant user info.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        handler=_memory_search,
    ),
    "memory_write": ToolSpec(
        name="memory_write",
        description="Write durable memory about the user.",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "source": {"type": "string"},
            },
            "required": ["content"],
        },
        handler=_memory_write,
    ),
}


def build_openai_tools() -> List[Dict[str, Any]]:
    tools = []
    for spec in TOOL_SPECS.values():
        tools.append({
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        })
    return tools


def _system_prompt(ctx: ToolContext) -> str:
    return (
        "You are HushhVoice, a private, consent-first AI copilot. "
        "You can call tools to access email, calendar, profiles, and memory. "
        "Use tools when needed; do not fabricate personal data or messages. "
        "Only send email or create calendar events if the user explicitly asks. "
        "Validate email addresses; if an address looks invalid or ambiguous, ask for confirmation instead of sending. "
        "If a tool returns a missing_google_token error, tell the user to connect Google. "
        f"UserId: {ctx.user_id or 'unknown'}; UserEmail: {ctx.user_email or 'unknown'}."
    )


def _tool_call_from_msg(msg: Any) -> List[Any]:
    if isinstance(msg, dict):
        return msg.get("tool_calls") or []
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        return msg.tool_calls
    return []


def _parse_args(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def run_agentic_query(
    prompt: str,
    user_id: str,
    google_token: Optional[str] = None,
    user_email: Optional[str] = None,
    locale: Optional[str] = None,
    timezone: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not client:
        msg = "(offline) OpenAI client not configured."
        return {"speech": msg, "display": msg}

    ctx = ToolContext(
        user_id=user_id or "",
        google_token=google_token,
        user_email=user_email,
        locale=locale,
        timezone=timezone,
        request_id=request_id,
    )
    tools = build_openai_tools()

    if debug_enabled():
        record_event(
            "agent",
            "run_agentic_query start",
            data={
                "user_id": ctx.user_id,
                "user_email": ctx.user_email,
                "prompt": prompt[:400],
            },
            request_id=ctx.request_id,
        )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(ctx)},
        {"role": "user", "content": prompt},
    ]

    for _ in range(MAX_TOOL_STEPS):
        if debug_enabled():
            record_event(
                "openai",
                "chat.completions.create",
                data={"model": OPENAI_MODEL, "tool_choice": "auto"},
                request_id=ctx.request_id,
            )
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=600,
        )
        msg = resp.choices[0].message
        tool_calls = _tool_call_from_msg(msg)

        if tool_calls:
            if debug_enabled():
                record_event(
                    "openai",
                    "tool_calls received",
                    data={"count": len(tool_calls)},
                    request_id=ctx.request_id,
                )
            assistant_tool_calls = []
            for call in tool_calls:
                if isinstance(call, dict):
                    assistant_tool_calls.append(call)
                else:
                    assistant_tool_calls.append({
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    })
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": assistant_tool_calls,
            })
            for call in tool_calls:
                try:
                    if isinstance(call, dict):
                        name = (call.get("function") or {}).get("name") or ""
                        args = _parse_args((call.get("function") or {}).get("arguments") or "")
                    else:
                        name = call.function.name
                        args = _parse_args(call.function.arguments)
                except Exception:
                    name = ""
                    args = {}

                spec = TOOL_SPECS.get(name)
                if debug_enabled():
                    record_event(
                        "tool",
                        f"call {name or 'unknown'}",
                        data={"args": args},
                        request_id=ctx.request_id,
                    )
                if not spec:
                    result = _tool_err(f"Unknown tool: {name}", "unknown_tool")
                else:
                    result = spec.handler(args, ctx)
                if debug_enabled():
                    record_event(
                        "tool",
                        f"result {name or 'unknown'}",
                        data={"ok": bool(result.get("ok")), "error": result.get("error")},
                        request_id=ctx.request_id,
                        level="error" if not result.get("ok") else "info",
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id") if isinstance(call, dict) else call.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            continue

        content = (msg.content or "").strip()
        if not content:
            content = "I couldn't generate a response."

        speech = content.replace("**", "").replace("```", "").strip()
        speech = speech[:350] if len(speech) > 350 else speech
        if debug_enabled():
            record_event(
                "agent",
                "run_agentic_query end",
                data={"response_chars": len(content)},
                request_id=ctx.request_id,
            )
        return {"speech": speech, "display": content}

    fallback = "I had trouble completing that request. Please try again."
    return {"speech": fallback, "display": fallback}
