from __future__ import annotations

from flask import Blueprint, Response, request
from flask_cors import cross_origin

from services.tts_service import synthesize
from utils.errors import ServiceError
from utils.json_helpers import jerror

tts_bp = Blueprint("tts", __name__)


# =========================
# Text-to-Speech Endpoint
# =========================
@tts_bp.post("/tts")
@cross_origin()
def tts():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = (data.get("voice") or "alloy").strip()

    try:
        audio_bytes = synthesize(text, voice)
        return Response(audio_bytes, mimetype="audio/mpeg")
    except ServiceError as e:
        return jerror(e.message, e.status, e.code)
