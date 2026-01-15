from __future__ import annotations

import re
from typing import Any, Dict

from storage.profile_store import load_profile, save_profile
from storage.supabase_store import supabase_enabled
from utils.errors import ServiceError


def _is_valid_email(email: str) -> bool:
    return bool(email) and "@" in email and "." in email.split("@")[-1]


def _is_valid_phone(phone: str) -> bool:
    return bool(re.search(r"\d", phone or ""))


def get_profile(user_id: str) -> Dict[str, Any]:
    if not supabase_enabled():
        raise ServiceError("Supabase not configured", 500)

    row = load_profile(user_id)
    if not row:
        return {"exists": False, "profile": None}
    return {"exists": True, "profile": row}


def upsert_profile(user_id: str, full_name: str, phone: str, email: str) -> Dict[str, Any]:
    if not full_name or not phone or not email:
        raise ServiceError("full_name, phone, and email are required.", 400)
    if not _is_valid_email(email):
        raise ServiceError("Invalid email format.", 400)
    if not _is_valid_phone(phone):
        raise ServiceError("Invalid phone format.", 400)

    if not supabase_enabled():
        raise ServiceError("Supabase not configured", 500)

    saved = save_profile(user_id, full_name, phone, email)
    if not saved:
        raise ServiceError("Failed to save profile", 500)
    return {"saved": True, "profile": saved}
