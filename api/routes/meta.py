from __future__ import annotations

from flask import Blueprint

from clients.openai_client import client
from config import APP_NAME, APP_VERSION, VERIFY_GOOGLE_TOKEN
from utils.json_helpers import jok

meta_bp = Blueprint("meta", __name__)


# =========================
# Meta / Health
# =========================
@meta_bp.get("/health")
def health():
    return jok(
        {
            "name": APP_NAME,
            "version": APP_VERSION,
            "openai": bool(client),
            "verify_google_token": VERIFY_GOOGLE_TOKEN,
        }
    )


@meta_bp.get("/version")
def version():
    return jok({"name": APP_NAME, "version": APP_VERSION})
