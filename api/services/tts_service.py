from __future__ import annotations

from clients.openai_client import client
from config import log
from utils.errors import ServiceError


def synthesize(text: str, voice: str) -> bytes:
    if not client:
        raise ServiceError("OpenAI client not configured", 500, "no_client")

    if not text:
        raise ServiceError("Missing 'text' in request body", 400)

    try:
        result = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
        )
        return result.read()
    except Exception as e:
        log.exception("TTS generation error")
        raise ServiceError(f"TTS generation failed: {e}", 500) from e
