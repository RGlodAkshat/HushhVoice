from __future__ import annotations

import json
import os
from threading import Lock
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


MEMORY_STORE_PATH = os.getenv("HUSHH_MEMORY_STORE_PATH", "/tmp/hushh_memory_store.json")
SUPABASE_MEMORY_TABLE = os.getenv("HUSHHVOICE_MEMORY_TABLE_SUPABASE", "hushh_memory_store")
SUPABASE_MEMORY_COLUMN = os.getenv("HUSHHVOICE_MEMORY_COLUMN_SUPABASE", "memory")

_LOCK = Lock()


def _ensure_dir() -> None:
    try:
        os.makedirs(os.path.dirname(MEMORY_STORE_PATH) or "/tmp", exist_ok=True)
    except Exception:
        pass


def _load_all() -> Dict[str, List[Dict[str, Any]]]:
    _ensure_dir()
    if not os.path.exists(MEMORY_STORE_PATH):
        return {}
    try:
        with open(MEMORY_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        log.exception("Failed to load memory store")
        return {}


def _save_all(data: Dict[str, List[Dict[str, Any]]]) -> None:
    _ensure_dir()
    try:
        with open(MEMORY_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("Failed to save memory store")


def load_memory(user_id: str) -> List[Dict[str, Any]]:
    if not user_id:
        return []
    with _LOCK:
        data = _load_all()
        return list(data.get(user_id, []))


def save_memory(user_id: str, entries: List[Dict[str, Any]]) -> None:
    if not user_id:
        return
    with _LOCK:
        data = _load_all()
        data[user_id] = entries
        _save_all(data)


def append_memory(user_id: str, entry: Dict[str, Any]) -> None:
    if not user_id:
        return
    with _LOCK:
        data = _load_all()
        data.setdefault(user_id, [])
        data[user_id].append(entry)
        _save_all(data)


def _supabase_enabled() -> bool:
    return supabase_enabled()


def _supabase_table_url() -> str:
    return supabase_table_url(SUPABASE_MEMORY_TABLE)


def load_memory_from_supabase(user_id: str) -> Optional[List[Dict[str, Any]]]:
    if not _supabase_enabled():
        return None
    if SUPABASE_MEMORY_TABLE == "memories":
        url = f"{_supabase_table_url()}?user_id=eq.{quote(user_id, safe='')}&select=memory_id,content,source,created_at,updated_at"
        try:
            resp = supabase_get(url, headers=supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
            if resp.status_code >= 400:
                log.warning("Supabase memories load failed: %s", resp.text)
                return None
            rows = resp.json() or []
            if not rows:
                return None
            entries: List[Dict[str, Any]] = []
            for row in rows:
                entries.append({
                    "id": row.get("memory_id"),
                    "content": row.get("content") or "",
                    "tags": [],
                    "source": row.get("source") or "memory",
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                    "embedding": None,
                })
            return entries
        except Exception:
            log.exception("Failed to load memories from Supabase")
            return None
    url = f"{_supabase_table_url()}?user_id=eq.{quote(user_id, safe='')}&select={SUPABASE_MEMORY_COLUMN}"
    try:
        resp = supabase_get(url, headers=supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase memory load failed: %s", resp.text)
            return None
        rows = resp.json() or []
        if not rows:
            return None
        mem = rows[0].get(SUPABASE_MEMORY_COLUMN)
        return mem if isinstance(mem, list) else None
    except Exception:
        log.exception("Failed to load memory from Supabase")
        return None


def save_memory_to_supabase(user_id: str, entries: List[Dict[str, Any]]) -> bool:
    if not _supabase_enabled():
        return False
    if SUPABASE_MEMORY_TABLE == "memories":
        # Row-per-memory is handled by memory_store_v2.create_memory.
        return True
    url = _supabase_table_url()
    headers = supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    payload = {"user_id": user_id, SUPABASE_MEMORY_COLUMN: entries}
    try:
        resp = supabase_post(url, headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase memory save failed: %s", resp.text)
            return False
        return True
    except Exception:
        log.exception("Failed to save memory to Supabase")
        return False
