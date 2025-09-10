# agent/auth.py
from google.oauth2 import id_token
from google.auth.transport import requests as grequests

def verify_google_id_token(id_token_str: str, client_id: str) -> dict:
    """
    Validates a Google ID token (One-Tap / Sign-In) and returns user info.
    Raises ValueError on invalid tokens.
    """
    payload = id_token.verify_oauth2_token(
        id_token_str,
        grequests.Request(),
        audience=client_id,
    )
    # payload includes: email, email_verified, name, picture, sub, etc.
    return {
        "email": payload.get("email"),
        "sub": payload.get("sub"),
        "name": payload.get("name"),
    }


