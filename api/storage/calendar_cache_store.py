from __future__ import annotations

import os
from typing import Any, Dict, List
from urllib.parse import quote

from config import log
from storage.supabase_store import (
    SUPABASE_TIMEOUT_SECS,
    supabase_enabled,
    supabase_get,
    supabase_headers,
    supabase_post,
    supabase_table_url,
)


SUPABASE_CAL_CACHE_TABLE = os.environ.get("HUSHHVOICE_CAL_CACHE_TABLE_SUPABASE", "calendar_event_cache")


def _enabled() -> bool:
    return supabase_enabled()


def _table_url() -> str:
    return supabase_table_url(SUPABASE_CAL_CACHE_TABLE)


def get_cached_events(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    if not _enabled():
        return []
    url = (
        f"{_table_url()}?user_id=eq.{quote(user_id, safe='')}"
        f"&order=start_time.desc&limit={int(limit)}&select=*"
    )
    try:
        resp = supabase_get(url, headers=supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase get_cached_events failed: %s", resp.text)
            return []
        return resp.json() or []
    except Exception:
        log.exception("Supabase get_cached_events error")
        return []


def upsert_events(user_id: str, events: List[Dict[str, Any]]) -> bool:
    if not _enabled():
        return True
    if not events:
        return True
    payload = []
    for ev in events:
        payload.append({
            "user_id": user_id,
            "event_id": ev.get("id"),
            "summary": ev.get("summary"),
            "start_time": ev.get("start"),
            "end_time": ev.get("end"),
            "location": ev.get("location"),
            "attendees": ev.get("attendees"),
            "html_link": ev.get("htmlLink"),
            "raw": ev,
        })
    headers = supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates"
    try:
        resp = supabase_post(_table_url(), headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase upsert_events failed: %s", resp.text)
            return False
        return True
    except Exception:
        log.exception("Supabase upsert_events error")
        return False
