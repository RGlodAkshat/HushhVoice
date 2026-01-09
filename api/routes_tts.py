from __future__ import annotations

from flask import Response, request
from flask_cors import cross_origin

from app_context import app, client, log
from json_helpers import jerror


# =========================
# Text-to-Speech Endpoint
# =========================
@app.post("/tts")
@cross_origin()
def tts():
    if not client:
        return jerror("OpenAI client not configured", 500, "no_client")

    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = (data.get("voice") or "alloy").strip()

    if not text:
        return jerror("Missing 'text' in request body", 400)

    try:
        result = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
        )
        audio_bytes = result.read()  # get full MP3 bytes
        return Response(audio_bytes, mimetype="audio/mpeg")
    except Exception as e:
        log.exception("TTS generation error")
        return jerror(f"TTS generation failed: {e}", 500)
