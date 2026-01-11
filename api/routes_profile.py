from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests
from flask import request

from app_context import app, log
from json_helpers import jerror, jok


SUPABASE_URL = os.environ.get("HUSHHVOICE_URL_SUPABASE", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("HUSHHVOICE_SERVICE_ROLE_KEY_SUPABASE", "")
SUPABASE_PROFILE_TABLE = os.environ.get("HUSHHVOICE_PROFILE_TABLE_SUPABASE", "kai_user_profile")
SUPABASE_TIMEOUT_SECS = float(os.environ.get("HUSHHVOICE_SUPABASE_TIMEOUT_SECS", "5"))


def _supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _supabase_table_url() -> str:
    return f"{SUPABASE_URL}/rest/v1/{SUPABASE_PROFILE_TABLE}"


def _supabase_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _get_user_id() -> str:
    uid = request.args.get("user_id") or request.headers.get("X-User-Id")
    if uid:
        return uid.strip()
    data = request.get_json(force=True, silent=True) or {}
    uid = data.get("user_id")
    return (uid or "dev-anon").strip()


def _is_valid_email(email: str) -> bool:
    return bool(email) and "@" in email and "." in email.split("@")[-1]


def _is_valid_phone(phone: str) -> bool:
    return bool(re.search(r"\d", phone or ""))


def _load_profile(user_id: str) -> Optional[Dict[str, Any]]:
    if not _supabase_enabled():
        return None
    url = f"{_supabase_table_url()}?user_id=eq.{quote(user_id, safe='')}&select=user_id,full_name,phone,email"
    try:
        resp = requests.get(url, headers=_supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
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


def _save_profile(user_id: str, full_name: str, phone: str, email: str) -> Optional[Dict[str, Any]]:
    if not _supabase_enabled():
        return None
    url = _supabase_table_url()
    headers = _supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    payload = {
        "user_id": user_id,
        "full_name": full_name,
        "phone": phone,
        "email": email,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase profile save failed: %s", resp.text)
            return None
        rows = resp.json() or []
        return rows[0] if rows else payload
    except Exception:
        log.exception("Failed to save profile to Supabase")
        return None


@app.get("/profile")
def profile_get():
    user_id = _get_user_id()
    if not _supabase_enabled():
        return jerror("Supabase not configured", 500)

    row = _load_profile(user_id)
    if not row:
        return jok({"exists": False, "profile": None})
    return jok({"exists": True, "profile": row})


@app.post("/profile")
def profile_upsert():
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()
    full_name = (data.get("full_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip().lower()

    if not full_name or not phone or not email:
        return jerror("full_name, phone, and email are required.", 400)
    if not _is_valid_email(email):
        return jerror("Invalid email format.", 400)
    if not _is_valid_phone(phone):
        return jerror("Invalid phone format.", 400)

    if not _supabase_enabled():
        return jerror("Supabase not configured", 500)

    saved = _save_profile(user_id, full_name, phone, email)
    if not saved:
        return jerror("Failed to save profile", 500)
    return jok({"saved": True, "profile": saved})
