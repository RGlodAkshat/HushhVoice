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


SUPABASE_MEMORIES_TABLE = os.environ.get("HUSHHVOICE_MEMORIES_TABLE_SUPABASE", "memories")


def _enabled() -> bool:
    return supabase_enabled()


def _table_url() -> str:
    return supabase_table_url(SUPABASE_MEMORIES_TABLE)


def create_memory(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _enabled():
        return payload
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"
    try:
        resp = supabase_post(_table_url(), headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase create_memory failed: %s", resp.text)
            return None
        rows = resp.json() or []
        return rows[0] if rows else payload
    except Exception:
        log.exception("Supabase create_memory error")
        return None


def list_memories(user_id: str) -> Optional[list]:
    if not _enabled():
        return None
    url = f"{_table_url()}?user_id=eq.{quote(user_id, safe='')}&select=*"
    try:
        resp = supabase_get(url, headers=supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase list_memories failed: %s", resp.text)
            return None
        return resp.json() or []
    except Exception:
        log.exception("Supabase list_memories error")
        return None
