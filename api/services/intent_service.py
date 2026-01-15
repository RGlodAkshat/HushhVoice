from __future__ import annotations

from clients.openai_client import client
from config import log


# =========================
# Shared helpers for Siri + Web
# =========================
def classify_intent_text(user_text: str) -> str:
    """
    Classify a natural language query into one of:
      read_email, send_email, schedule_event, calendar_answer, health, general
    Uses the same responses+tools pattern as /intent/classify.
    """
    text = (user_text or "").strip()
    if not text:
        return "general"

    intent = "general"
    try:
        tools = [{
            "type": "function",
            "name": "classify_intent",
            "description": "Classify the user's query into one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": [
                            "read_email",
                            "send_email",
                            "schedule_event",
                            "calendar_answer",
                            "health",
                            "general",
                        ],
                    }
                },
                "required": ["intent"],
                "additionalProperties": False,
            },
            "strict": True,
        }]

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict intent classifier for a personal AI assistant. "
                        "Classify user queries into exactly one of: "
                        "read_email, send_email, schedule_event, calendar_answer, health, general."
                    ),
                },
                {"role": "user", "content": text},
            ],
            tools=tools,
            tool_choice={"type": "function", "name": "classify_intent"},
        )

        for item in resp.output:
            if item.type == "function_call" and item.name == "classify_intent":
                import json as _json
                args = _json.loads(item.arguments)
                intent = args.get("intent", "general")
                break
    except Exception as e:
        log.warning("Intent classify error (helper): %s", e)
        intent = "general"

    return intent
