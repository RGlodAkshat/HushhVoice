from __future__ import annotations

from typing import Dict, Iterable, Optional
from urllib.parse import quote

import os
import requests
from flask import request

from app_context import app, log
from json_helpers import jerror, jok
from routes_onboarding_agent import _cache_clear, _delete_state_from_supabase, _state_path


SUPABASE_URL = os.environ.get("HUSHHVOICE_URL_SUPABASE", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("HUSHHVOICE_SERVICE_ROLE_KEY_SUPABASE", "")
SUPABASE_PROFILE_TABLE = os.environ.get("HUSHHVOICE_PROFILE_TABLE_SUPABASE", "kai_user_profile")
SUPABASE_TIMEOUT_SECS = float(os.environ.get("HUSHHVOICE_SUPABASE_TIMEOUT_SECS", "5"))


def _supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _supabase_profile_url() -> str:
    return f"{SUPABASE_URL}/rest/v1/{SUPABASE_PROFILE_TABLE}"


def _supabase_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _delete_profile_from_supabase(user_id: str) -> bool:
    if not _supabase_enabled():
        return False
    url = f"{_supabase_profile_url()}?user_id=eq.{quote(user_id, safe='')}"
    headers = _supabase_headers()
    headers["Prefer"] = "return=minimal"
    try:
        resp = requests.delete(url, headers=headers, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase profile delete failed: %s", resp.text)
            return False
        return True
    except Exception:
        log.exception("Failed to delete profile from Supabase")
        return False


def _delete_onboarding_disk_state(user_id: str) -> None:
    try:
        path = _state_path(user_id)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        log.exception("Failed to delete onboarding state from disk")


def _unique_ids(values: Iterable[Optional[str]]) -> list[str]:
    out = []
    for v in values:
        if not v:
            continue
        s = v.strip()
        if s and s not in out:
            out.append(s)
    return out


@app.post("/account/delete")
def account_delete():
    """
    Deletes onboarding + profile data for a user from Supabase and local disk state.
    Body:
      { user_id?: str, apple_user_id?: str, kai_user_id?: str }
    """
    data = request.get_json(force=True, silent=True) or {}
    user_ids = _unique_ids([
        data.get("user_id"),
        data.get("apple_user_id"),
        data.get("kai_user_id"),
    ])

    if not user_ids:
        return jerror("Missing user_id", 400)

    if not _supabase_enabled():
        return jerror("Supabase not configured", 500)

    errors = []
    for uid in user_ids:
        _cache_clear(uid)
        _delete_onboarding_disk_state(uid)
        _delete_state_from_supabase(uid)
        if not _delete_profile_from_supabase(uid):
            errors.append(uid)

    if errors:
        return jerror(f"Supabase delete failed for: {', '.join(errors)}", 500)

    return jok({"ok": True, "user_ids": user_ids})
