from __future__ import annotations

from flask import Blueprint, request

from services.account_service import delete_account_data
from utils.errors import ServiceError
from utils.json_helpers import jerror, jok

account_bp = Blueprint("account", __name__)


@account_bp.post("/account/delete")
def account_delete():
    """
    Deletes onboarding + profile data for a user from Supabase and local disk state.
    Body:
      { user_id?: str, apple_user_id?: str, kai_user_id?: str }
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        out = delete_account_data([
            data.get("user_id"),
            data.get("apple_user_id"),
            data.get("kai_user_id"),
        ])
        return jok(out)
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)
