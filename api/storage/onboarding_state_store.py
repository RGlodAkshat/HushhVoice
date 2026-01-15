from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from threading import Lock
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


SUPABASE_ONBOARDING_TABLE = os.environ.get("HUSHHVOICE_ONBOARDING_TABLE_SUPABASE", "kai_onboarding_state")
SUPABASE_ONBOARDING_STATE_COLUMN = os.environ.get("HUSHHVOICE_ONBOARDING_STATE_COLUMN", "state")
STATE_CACHE_TTL_SECS = int(os.environ.get("HUSHH_ONBOARDING_CACHE_TTL", "5"))

# In-memory cache (dev). Local disk is source of truth during onboarding.
_STATE_BY_USER: Dict[str, Dict[str, Any]] = {}
_STATE_BY_USER_TS: Dict[str, float] = {}
_STATE_LOCK = Lock()


def _now_iso() -> str:
    return datetime.now().isoformat()


def _state_dir() -> str:
    base = os.environ.get("HUSHH_ONBOARDING_STATE_DIR", "/tmp/hushh_onboarding_state")
    os.makedirs(base, exist_ok=True)
    return base


def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", user_id or "dev-anon")


def _state_path(user_id: str) -> str:
    return os.path.join(_state_dir(), f"{_safe_user_id(user_id)}.json")


def _supabase_enabled() -> bool:
    return supabase_enabled()


def _supabase_table_url() -> str:
    return supabase_table_url(SUPABASE_ONBOARDING_TABLE)


def _supabase_headers() -> Dict[str, str]:
    return supabase_headers()


def _cache_get(user_id: str) -> Optional[Dict[str, Any]]:
    if STATE_CACHE_TTL_SECS <= 0:
        return None
    now = time.time()
    with _STATE_LOCK:
        ts = _STATE_BY_USER_TS.get(user_id)
        if not ts:
            return None
        if now - ts > STATE_CACHE_TTL_SECS:
            _STATE_BY_USER.pop(user_id, None)
            _STATE_BY_USER_TS.pop(user_id, None)
            return None
        return _STATE_BY_USER.get(user_id)


def _cache_set(user_id: str, st: Dict[str, Any]) -> None:
    if STATE_CACHE_TTL_SECS <= 0:
        return
    with _STATE_LOCK:
        _STATE_BY_USER[user_id] = st
        _STATE_BY_USER_TS[user_id] = time.time()


def _cache_clear(user_id: str) -> None:
    with _STATE_LOCK:
        _STATE_BY_USER.pop(user_id, None)
        _STATE_BY_USER_TS.pop(user_id, None)


def _load_state_from_supabase(user_id: str) -> Optional[Dict[str, Any]]:
    if not _supabase_enabled():
        return None
    url = f"{_supabase_table_url()}?user_id=eq.{quote(user_id, safe='')}&select={SUPABASE_ONBOARDING_STATE_COLUMN}"
    try:
        resp = supabase_get(url, headers=_supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase load failed: %s", resp.text)
            return None
        rows = resp.json() or []
        if not rows:
            return None
        state = rows[0].get(SUPABASE_ONBOARDING_STATE_COLUMN)
        return state if isinstance(state, dict) else None
    except Exception:
        log.exception("Failed to load state from Supabase")
        return None


def _load_state_from_disk(user_id: str) -> Optional[Dict[str, Any]]:
    path = _state_path(user_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("Failed to load state from disk")
        return None


def _load_state(user_id: str) -> Optional[Dict[str, Any]]:
    cached = _cache_get(user_id)
    if cached is not None:
        return cached

    st = _load_state_from_disk(user_id)
    if st is not None:
        _cache_set(user_id, st)
    return st


def _save_state_to_supabase(user_id: str, st: Dict[str, Any]) -> bool:
    if not _supabase_enabled():
        log.info("[Onboarding] Supabase disabled; skipping save user_id=%s", user_id)
        return False
    url = _supabase_table_url()
    headers = _supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    payload = {"user_id": user_id, SUPABASE_ONBOARDING_STATE_COLUMN: st}
    try:
        resp = supabase_post(url, headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase save failed: status=%s body=%s", resp.status_code, resp.text)
            return False
        log.info("[Onboarding] Supabase save ok user_id=%s table=%s", user_id, SUPABASE_ONBOARDING_TABLE)
        return True
    except Exception:
        log.exception("Failed to save state to Supabase")
        return False


def _save_state_to_disk(user_id: str, st: Dict[str, Any]) -> None:
    path = _state_path(user_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("Failed to save state to disk")


def _save_state(user_id: str, st: Dict[str, Any]) -> None:
    _cache_set(user_id, st)
    _save_state_to_disk(user_id, st)


def _delete_state_from_supabase(user_id: str) -> None:
    if not _supabase_enabled():
        return
    url = f"{_supabase_table_url()}?user_id=eq.{quote(user_id, safe='')}"
    headers = _supabase_headers()
    headers["Prefer"] = "return=minimal"
    try:
        resp = supabase_delete(url, headers=headers, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase delete failed: %s", resp.text)
    except Exception:
        log.exception("Failed to delete state from Supabase")


def _delete_state_from_disk(user_id: str, log_errors: bool = True) -> None:
    try:
        path = _state_path(user_id)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        if log_errors:
            log.exception("Failed to delete onboarding state from disk")
