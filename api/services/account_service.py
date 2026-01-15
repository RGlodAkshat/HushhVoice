from __future__ import annotations

from typing import Iterable, Optional, Dict, Any

from storage.onboarding_state_store import _cache_clear, _delete_state_from_disk, _delete_state_from_supabase
from storage.profile_store import delete_profile
from storage.supabase_store import supabase_enabled
from utils.errors import ServiceError


def _unique_ids(values: Iterable[Optional[str]]) -> list[str]:
    out = []
    for v in values:
        if not v:
            continue
        s = v.strip()
        if s and s not in out:
            out.append(s)
    return out


def delete_account_data(user_ids: Iterable[Optional[str]]) -> Dict[str, Any]:
    ids = _unique_ids(user_ids)
    if not ids:
        raise ServiceError("Missing user_id", 400)

    if not supabase_enabled():
        raise ServiceError("Supabase not configured", 500)

    errors = []
    for uid in ids:
        _cache_clear(uid)
        _delete_state_from_disk(uid)
        _delete_state_from_supabase(uid)
        if not delete_profile(uid):
            errors.append(uid)

    if errors:
        raise ServiceError(f"Supabase delete failed for: {', '.join(errors)}", 500)

    return {"ok": True, "user_ids": ids}
