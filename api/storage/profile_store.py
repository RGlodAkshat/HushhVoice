from __future__ import annotations

import os
from typing import Any, Dict, Optional
from urllib.parse import quote

from config import log
from storage.supabase_store import (
    SUPABASE_TIMEOUT_SECS,
    supabase_delete,
    supabase_enabled,
    supabase_get,
    supabase_headers,
    supabase_post,
    supabase_table_url,
)


SUPABASE_PROFILE_TABLE = os.environ.get("HUSHHVOICE_PROFILE_TABLE_SUPABASE", "kai_user_profile")


def _supabase_enabled() -> bool:
    return supabase_enabled()


def _supabase_profile_url() -> str:
    return supabase_table_url(SUPABASE_PROFILE_TABLE)


def _supabase_headers() -> Dict[str, str]:
    return supabase_headers()


def load_profile(user_id: str) -> Optional[Dict[str, Any]]:
    if not _supabase_enabled():
        return None
    url = f"{_supabase_profile_url()}?user_id=eq.{quote(user_id, safe='')}&select=user_id,full_name,phone,email"
    try:
        resp = supabase_get(url, headers=_supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase profile load failed: %s", resp.text)
            return None
        rows = resp.json() or []
        if not rows:
            return None
        return rows[0]
    except Exception:
        log.exception("Failed to load profile from Supabase")
        return None


def save_profile(user_id: str, full_name: str, phone: str, email: str) -> Optional[Dict[str, Any]]:
    if not _supabase_enabled():
        return None
    url = _supabase_profile_url()
    headers = _supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    payload = {
        "user_id": user_id,
        "full_name": full_name,
        "phone": phone,
        "email": email,
    }
    try:
        resp = supabase_post(url, headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase profile save failed: %s", resp.text)
            return None
        rows = resp.json() or []
        return rows[0] if rows else payload
    except Exception:
        log.exception("Failed to save profile to Supabase")
        return None


def delete_profile(user_id: str) -> bool:
    if not _supabase_enabled():
        return False
    url = f"{_supabase_profile_url()}?user_id=eq.{quote(user_id, safe='')}"
    headers = _supabase_headers()
    headers["Prefer"] = "return=minimal"
    try:
        resp = supabase_delete(url, headers=headers, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase profile delete failed: %s", resp.text)
            return False
        return True
    except Exception:
        log.exception("Failed to delete profile from Supabase")
        return False
