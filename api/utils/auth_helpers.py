from __future__ import annotations

from typing import Any, Dict, Optional

from flask import request

from config import VERIFY_GOOGLE_TOKEN, google_requests, id_token, log


# =========================
# Auth helpers
# =========================
def verify_google_token_if_enabled() -> Optional[Dict[str, Any]]:
    """Verifies Google ID token when enabled. Independent from Gmail access token."""
    if not VERIFY_GOOGLE_TOKEN:
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        payload = id_token.verify_oauth2_token(token, google_requests.Request())
        return payload  # contains 'email', etc.
    except Exception as e:
        log.warning("Google ID token verification failed: %s", e)
        return None


def get_access_token_from_request(data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Gmail/Calendar require an OAuth access token with appropriate scopes.
    We accept it either in header 'X-Google-Access-Token' or JSON body 'access_token'.
    """
    token = request.headers.get("X-Google-Access-Token")
    if token:
        return token.strip()
    if data:
        t = (data.get("access_token") or "").strip()
        if t:
            return t
    return None
