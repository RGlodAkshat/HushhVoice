from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
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


SUPABASE_GMAIL_CACHE_TABLE = os.environ.get("HUSHHVOICE_GMAIL_CACHE_TABLE_SUPABASE", "gmail_message_index")


def _enabled() -> bool:
    return supabase_enabled()


def _table_url() -> str:
    return supabase_table_url(SUPABASE_GMAIL_CACHE_TABLE)


def get_cached_messages(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    if not _enabled():
        return []
    url = (
        f"{_table_url()}?user_id=eq.{quote(user_id, safe='')}"
        f"&order=internal_date.desc&limit={int(limit)}&select=*"
    )
    try:
        resp = supabase_get(url, headers=supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase get_cached_messages failed: %s", resp.text)
            return []
        return resp.json() or []
    except Exception:
        log.exception("Supabase get_cached_messages error")
        return []


def upsert_messages(user_id: str, messages: List[Dict[str, Any]]) -> bool:
    if not _enabled():
        return True
    if not messages:
        return True
    payload = []
    for msg in messages:
        payload.append({
            "user_id": user_id,
            "message_id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "internal_date": msg.get("date_iso"),
            "from_email": msg.get("from_email"),
            "from_name": msg.get("from"),
            "subject": msg.get("subject"),
            "date_label": msg.get("date"),
            "snippet": msg.get("snippet"),
            "raw": msg,
        })
    headers = supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates"
    try:
        resp = supabase_post(_table_url(), headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase upsert_messages failed: %s", resp.text)
            return False
        return True
    except Exception:
        log.exception("Supabase upsert_messages error")
        return False
