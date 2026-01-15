from __future__ import annotations

from flask import Blueprint, request

from config import log
from services.intent_service import classify_intent_text
from utils.json_helpers import jok

intent_bp = Blueprint("intent", __name__)


# =========================
# Intent Classifier (web)
# =========================
@intent_bp.post("/intent/classify")
def intent_classify_route():
    data = request.get_json(force=True, silent=True) or {}
    user_text = (data.get("query") or "").strip()
    intent = classify_intent_text(user_text)
    log.info("[IntentClassifier] User: %s", user_text)
    log.info("[IntentClassifier] Intent: %s", intent)
    return jok({"intent": intent})
