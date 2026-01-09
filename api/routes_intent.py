from __future__ import annotations

from app_context import app, log
from intent_helpers import classify_intent_text
from json_helpers import jok
from flask import request


# =========================
# Intent Classifier (web)
# =========================
@app.post("/intent/classify")
def intent_classify_route():
    data = request.get_json(force=True, silent=True) or {}
    user_text = (data.get("query") or "").strip()
    intent = classify_intent_text(user_text)
    log.info("[IntentClassifier] User: %s", user_text)
    log.info("[IntentClassifier] Intent: %s", intent)
    return jok({"intent": intent})
