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


SUPABASE_CONFIRM_TABLE = os.environ.get("HUSHHVOICE_CONFIRM_TABLE_SUPABASE", "confirmation_requests")


def _enabled() -> bool:
    return supabase_enabled()


def _table_url() -> str:
    return supabase_table_url(SUPABASE_CONFIRM_TABLE)


def create_confirmation(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _enabled():
        return payload
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"
    try:
        resp = supabase_post(_table_url(), headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase create_confirmation failed: %s", resp.text)
            return None
        rows = resp.json() or []
        return rows[0] if rows else payload
    except Exception:
        log.exception("Supabase create_confirmation error")
        return None


def update_confirmation(confirmation_id: str, updates: Dict[str, Any]) -> bool:
    if not _enabled():
        return True
    url = f"{_table_url()}?confirmation_request_id=eq.{quote(confirmation_id, safe='')}"
    headers = supabase_headers()
    headers["Prefer"] = "return=minimal"
    try:
        resp = supabase_post(url, headers=headers, json=updates, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase update_confirmation failed: %s", resp.text)
            return False
        return True
    except Exception:
        log.exception("Supabase update_confirmation error")
        return False


def get_confirmation(confirmation_id: str) -> Optional[Dict[str, Any]]:
    if not _enabled():
        return None
    url = f"{_table_url()}?confirmation_request_id=eq.{quote(confirmation_id, safe='')}&select=*"
    try:
        resp = supabase_get(url, headers=supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase get_confirmation failed: %s", resp.text)
            return None
        rows = resp.json() or []
        return rows[0] if rows else None
    except Exception:
        log.exception("Supabase get_confirmation error")
        return None
