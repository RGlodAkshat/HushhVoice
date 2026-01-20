from __future__ import annotations

import os
from typing import Any, Dict, Optional
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


SUPABASE_CACHE_STATE_TABLE = os.environ.get("HUSHHVOICE_CACHE_STATE_TABLE_SUPABASE", "cache_state")


def _enabled() -> bool:
    return supabase_enabled()


def _table_url() -> str:
    return supabase_table_url(SUPABASE_CACHE_STATE_TABLE)


def get_cache_state(user_id: str) -> Optional[Dict[str, Any]]:
    if not _enabled():
        return None
    url = f"{_table_url()}?user_id=eq.{quote(user_id, safe='')}&select=*"
    try:
        resp = supabase_get(url, headers=supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase get_cache_state failed: %s", resp.text)
            return None
        rows = resp.json() or []
        return rows[0] if rows else None
    except Exception:
        log.exception("Supabase get_cache_state error")
        return None


def upsert_cache_state(user_id: str, updates: Dict[str, Any]) -> bool:
    if not _enabled():
        return True
    payload = {"user_id": user_id, **updates}
    headers = supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates"
    try:
        resp = supabase_post(_table_url(), headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase upsert_cache_state failed: %s", resp.text)
            return False
        return True
    except Exception:
        log.exception("Supabase upsert_cache_state error")
        return False
