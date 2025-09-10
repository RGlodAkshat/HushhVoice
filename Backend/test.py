"""
===============================================================================
 test.py — Minimal Intent Classifier (latest SDK, function calling style)
 ------------------------------------------------------------------------------
 • Loads OPENAI_API_KEY from .env
 • You set `query` manually below
 • Uses OpenAI Responses API with tools (function calling)
 • Prints classified intent (general | mail | calendar | health | unknown)
===============================================================================
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Load API key from .env
# ---------------------------------------------------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("❌ Missing OPENAI_API_KEY in .env file")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------------------------
# Define a tool (function schema) for intent classification
# ---------------------------------------------------------------------------
tools = [
    {
        "type": "function",
        "name": "classify_intent",
        "description": "Classify the user's query into one of the known categories.",
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["general", "mail", "calendar", "health", "unknown"],
                    "description": "The intent category of the query"
                }
            },
            "required": ["intent"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]

# ---------------------------------------------------------------------------
# Query to classify (edit this string)
# ---------------------------------------------------------------------------
query = "Can you check my email and summarize important messages?"

# ---------------------------------------------------------------------------
# Run classification
# ---------------------------------------------------------------------------
response = client.responses.create(
    model="gpt-4o-mini",
    input=[
        {
            "role": "system",
            "content": (
                "You are an intent classifier. "
                "Classify the user's query into one of: general, mail, calendar, health.\n"
                "- 'mail': anything about reading, summarizing, drafting, replying to email.\n"
                "- 'calendar': scheduling, meetings, reminders, availability.\n"
                "- 'health': steps, sleep, fitness, wellness, or phone usage/wellbeing.\n"
                "- Otherwise: general."
            ),
        },
        {"role": "user", "content": query},
    ],
    tools=tools,
    tool_choice={"type": "function", "name": "classify_intent"},  # force the model to use this tool
)

# ---------------------------------------------------------------------------
# Extract tool call result
# ---------------------------------------------------------------------------
intent = "unknown"
for item in response.output:
    if item.type == "function_call" and item.name == "classify_intent":
        args = json.loads(item.arguments)
        intent = args.get("intent", "unknown")

print(f"[RESULT] Query: {query!r} → Intent: {intent!r}")
