from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agents.email_assistant.gmail_fetcher import (
    fetch_recent_emails,
    fetch_gmail_history,
    fetch_messages_by_ids,
    get_profile_history_id,
)
from clients.google_client import _google_get, _iso
from config import log
from storage.cache_state_store import get_cache_state, upsert_cache_state
from storage.calendar_cache_store import upsert_events
from storage.gmail_cache_store import upsert_messages
from utils.observability import log_event


GMAIL_CACHE_MAX = 60
CAL_CACHE_MAX = 250
GMAIL_CACHE_TTL_SECS = 120
CAL_CACHE_TTL_SECS = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_fresh(ts_iso: Optional[str], ttl_seconds: int) -> bool:
    if not ts_iso:
        return False
    try:
        dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return (_now() - dt).total_seconds() < ttl_seconds
    except Exception:
        return False


def _build_after_query(last_sync_iso: Optional[str], base_query: str) -> str:
    if not last_sync_iso:
        return base_query
    try:
        dt = datetime.fromisoformat(last_sync_iso.replace("Z", "+00:00"))
        after = dt.strftime("%Y/%m/%d")
        q = f"after:{after}"
        if base_query:
            q = f"{base_query} {q}"
        return q
    except Exception:
        return base_query


def refresh_gmail_cache(user_id: str, google_token: str, query: str = "") -> List[Dict[str, Any]]:
    state = get_cache_state(user_id) or {}
    last_sync = state.get("gmail_last_sync_ts")
    history_id = state.get("gmail_history_id")
    now_iso = _now().isoformat().replace("+00:00", "Z")

    # Prefer incremental sync if we have a history id and no specific query.
    if history_id and not query:
        try:
            changed_ids, new_history_id = fetch_gmail_history(
                google_token,
                start_history_id=history_id,
                max_results=GMAIL_CACHE_MAX,
            )
            emails: List[Dict[str, Any]] = []
            if changed_ids:
                emails = fetch_messages_by_ids(google_token, changed_ids, include_snippet=True)
                upsert_messages(user_id, emails)
            updates: Dict[str, Any] = {"gmail_last_sync_ts": now_iso}
            if new_history_id:
                updates["gmail_history_id"] = new_history_id
            upsert_cache_state(user_id, updates)
            log_event("cache", "gmail_incremental", data={"user_id": user_id, "count": len(emails)})
            return emails
        except Exception as exc:
            log.warning("gmail incremental sync failed: %s", exc)

    # Fallback to a bounded refresh.
    query = _build_after_query(last_sync, query)
    emails = fetch_recent_emails(
        access_token=google_token,
        max_results=GMAIL_CACHE_MAX,
        q=query or None,
        label_ids=None,
        include_snippet=True,
    )
    upsert_messages(user_id, emails)
    history_id = get_profile_history_id(google_token)
    updates: Dict[str, Any] = {"gmail_last_sync_ts": now_iso}
    if history_id:
        updates["gmail_history_id"] = history_id
    upsert_cache_state(user_id, updates)
    log_event("cache", "gmail_refresh", data={"user_id": user_id, "count": len(emails)})
    return emails


def refresh_calendar_cache(user_id: str, google_token: str) -> List[Dict[str, Any]]:
    state = get_cache_state(user_id) or {}
    sync_token = state.get("calendar_sync_token")
    time_min = _iso(_now() - timedelta(days=14))
    time_max = _iso(_now() + timedelta(days=60))

    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": CAL_CACHE_MAX,
    }
    if sync_token:
        params = {"syncToken": sync_token}

    try:
        resp = _google_get(google_token, "/calendars/primary/events", params)
    except Exception as exc:
        log.warning("calendar sync token failed: %s", exc)
        resp = _google_get(google_token, "/calendars/primary/events", {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": CAL_CACHE_MAX,
        })

    items = resp.get("items", []) or []
    events = []
    for e in items:
        if e.get("status") == "cancelled":
            continue
        events.append({
            "id": e.get("id"),
            "summary": e.get("summary") or "(No title)",
            "start": (e.get("start", {}) or {}).get("dateTime") or (e.get("start", {}) or {}).get("date"),
            "end": (e.get("end", {}) or {}).get("dateTime") or (e.get("end", {}) or {}).get("date"),
            "location": e.get("location"),
            "attendees": [a.get("email") for a in (e.get("attendees") or []) if a.get("email")],
            "htmlLink": e.get("htmlLink"),
        })
    upsert_events(user_id, events)
    if resp.get("nextSyncToken"):
        upsert_cache_state(user_id, {
            "calendar_sync_token": resp.get("nextSyncToken"),
            "calendar_last_sync_ts": _now().isoformat().replace("+00:00", "Z"),
        })
    log_event("cache", "calendar_refresh", data={"user_id": user_id, "count": len(events)})
    return events


def is_gmail_cache_fresh(user_id: str) -> bool:
    state = get_cache_state(user_id) or {}
    return _is_fresh(state.get("gmail_last_sync_ts"), GMAIL_CACHE_TTL_SECS)


def is_calendar_cache_fresh(user_id: str) -> bool:
    state = get_cache_state(user_id) or {}
    return _is_fresh(state.get("calendar_last_sync_ts"), CAL_CACHE_TTL_SECS)
