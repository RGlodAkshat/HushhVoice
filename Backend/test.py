import os
import json
from openai import OpenAI
from dotenv import load_dotenv

# Load env vars
load_dotenv()

print("🔥 test.py started")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
print("API key exists?", bool(os.getenv("OPENAI_API_KEY")))


# --- Classifier (tools/function-calling) ---
def intent_classify(user_text: str) -> str:
  tools = [{
    "type": "function",
    "name": "classify_intent",
    "description": "Classify the user's query into one category.",
    "parameters": {
      "type": "object",
      "properties": {
        "intent": {
          "type": "string",
          "enum": ["general", "mail", "calendar", "health", "unknown"]
        }
      },
      "required": ["intent"],
      "additionalProperties": False
    },
    "strict": True
  }]

  resp = client.responses.create(
    model="gpt-4o-mini",
    input=[
      {
        "role": "system",
        "content": (
          "You are an intent classifier. "
          "Classify into: general, mail, calendar, health.\n"
          "- 'mail': read/summarize/draft/reply email.\n"
          "- 'calendar': meetings, events, schedule, reminders.\n"
          "- 'health': steps, sleep, fitness, wellbeing/phone usage.\n"
          "- Otherwise: general."
        ),
      },
      {"role": "user", "content": user_text},
    ],
    tools=tools,
    tool_choice={"type": "function", "name": "classify_intent"},
  )
  intent = "unknown"
  for item in resp.output:
    if item.type == "function_call" and item.name == "classify_intent":
      args = json.loads(item.arguments)
      intent = args.get("intent", "unknown")
  return intent



if __name__ == "__main__":
    print("Running intent classifier test...")
    result = intent_classify("Can you read my latest emails?")
    print("Result:", result)
