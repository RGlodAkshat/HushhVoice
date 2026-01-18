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


SUPABASE_TURNS_TABLE = os.environ.get("HUSHHVOICE_TURNS_TABLE_SUPABASE", "chat_turns")


def _enabled() -> bool:
    return supabase_enabled()


def _table_url() -> str:
    return supabase_table_url(SUPABASE_TURNS_TABLE)


def create_turn(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _enabled():
        return payload
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"
    try:
        resp = supabase_post(_table_url(), headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase create_turn failed: %s", resp.text)
            return None
        rows = resp.json() or []
        return rows[0] if rows else payload
    except Exception:
        log.exception("Supabase create_turn error")
        return None


def update_turn(turn_id: str, updates: Dict[str, Any]) -> bool:
    if not _enabled():
        return True
    url = f"{_table_url()}?turn_id=eq.{quote(turn_id, safe='')}"
    headers = supabase_headers()
    headers["Prefer"] = "return=minimal"
    try:
        resp = supabase_post(url, headers=headers, json=updates, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase update_turn failed: %s", resp.text)
            return False
        return True
    except Exception:
        log.exception("Supabase update_turn error")
        return False


def get_turn(turn_id: str) -> Optional[Dict[str, Any]]:
    if not _enabled():
        return None
    url = f"{_table_url()}?turn_id=eq.{quote(turn_id, safe='')}&select=*"
    try:
        resp = supabase_get(url, headers=supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase get_turn failed: %s", resp.text)
            return None
        rows = resp.json() or []
        return rows[0] if rows else None
    except Exception:
        log.exception("Supabase get_turn error")
        return None
