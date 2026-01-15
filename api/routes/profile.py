from __future__ import annotations

from flask import Blueprint, request

from services.profile_service import get_profile, upsert_profile
from utils.errors import ServiceError
from utils.json_helpers import jerror, jok

profile_bp = Blueprint("profile", __name__)


def _get_user_id() -> str:
    uid = request.args.get("user_id") or request.headers.get("X-User-Id")
    if uid:
        return uid.strip()
    data = request.get_json(force=True, silent=True) or {}
    uid = data.get("user_id")
    return (uid or "dev-anon").strip()


@profile_bp.get("/profile")
def profile_get():
    user_id = _get_user_id()
    try:
        return jok(get_profile(user_id))
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)


@profile_bp.post("/profile")
def profile_upsert():
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()
    full_name = (data.get("full_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip().lower()

    try:
        return jok(upsert_profile(user_id, full_name, phone, email))
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)
