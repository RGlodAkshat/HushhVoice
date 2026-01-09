from __future__ import annotations

from app_context import APP_NAME, APP_VERSION, VERIFY_GOOGLE_TOKEN, app, client
from json_helpers import jok


# =========================
# Meta / Health
# =========================
@app.get("/health")
def health():
    return jok(
        {
            "name": APP_NAME,
            "version": APP_VERSION,
            "openai": bool(client),
            "verify_google_token": VERIFY_GOOGLE_TOKEN,
        }
    )


@app.get("/version")
def version():
    return jok({"name": APP_NAME, "version": APP_VERSION})
