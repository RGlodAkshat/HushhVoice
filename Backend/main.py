"""
===============================================================================
 HushhVoice Backend — main.py
 ------------------------------------------------------------------------------
 • /api/signin → verifies Google ID token (One Tap / Sign-In)
 • /api/echo   → single entrypoint:
       (1) classify intent via tools (general | mail | calendar | health)
       (2) route to handlers
       (3) return {intent, response, email}
 • Expects X-User-Email and (for mail/calendar) X-Google-Access-Token
===============================================================================
"""
import os
import json
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

from agent.auth import verify_google_id_token
from agent.mail import fetch_last_messages, answer_from_mail_context

# --- Env ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
if not OPENAI_API_KEY:
  raise RuntimeError("❌ Missing OPENAI_API_KEY in environment.")
if not GOOGLE_CLIENT_ID:
  print("⚠️ GOOGLE_CLIENT_ID not set — /api/signin will fail.")

# --- App ---
app = FastAPI(title="HushhVoice", version="0.3.0")
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

client = OpenAI(api_key=OPENAI_API_KEY)

# --- Models ---
class SignInIn(BaseModel):
  id_token: str
class SignInOut(BaseModel):
  email: str
  sub: Optional[str] = None
  name: Optional[str] = None
class EchoIn(BaseModel):
  prompt: str
class EchoOut(BaseModel):
  intent: Literal["general", "mail", "calendar", "health", "unknown"]
  response: str
  email: Optional[str] = None

# --- Sign-In ---
@app.post("/api/signin", response_model=SignInOut)
async def signin(data: SignInIn):
  if not GOOGLE_CLIENT_ID:
    raise HTTPException(status_code=500, detail="Server missing GOOGLE_CLIENT_ID")
  try:
    info = verify_google_id_token(data.id_token, GOOGLE_CLIENT_ID)
    return SignInOut(**info)
  except Exception as e:
    raise HTTPException(status_code=401, detail=f"Invalid ID token: {e}")

# --- Classifier (tools/function-calling) ---
def classify_intent(user_text: str) -> str:
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

# --- Handlers ---
def handle_general(user_text: str) -> str:
  r = client.responses.create(
    model="gpt-4o",
    instructions="You are HushhVoice, a concise, helpful AI copilot.",
    input=user_text,
    max_output_tokens=700,
  )
  return r.output_text or "I couldn't generate a response."

def handle_mail(user_text: str, gmail_access_token: str, max_results: int = 20) -> str:
  msgs = fetch_last_messages(gmail_access_token, max_results=max_results)
  return answer_from_mail_context(client, msgs, user_text)

def handle_calendar(user_text: str) -> str:
  return "(calendar) Not implemented yet."

def handle_health(user_text: str) -> str:
  return "(health) Not implemented yet."

# --- Unified endpoint ---
@app.post("/api/echo", response_model=EchoOut)
async def echo_with_intents(
  data: EchoIn,
  x_user_email: Optional[str] = Header(default=None, convert_underscores=False),
  x_google_access_token: Optional[str] = Header(default=None, convert_underscores=False),
):
  user_text = (data.prompt or "").strip()
  if not user_text:
    raise HTTPException(status_code=400, detail="prompt is required")

  try:
    intent = classify_intent(user_text)
  except Exception as e:
    print(f"[ERROR] classify failed: {e}")
    intent = "general"

  print(f"[DEBUG] Query={user_text!r} → Intent={intent!r}")

  if intent == "mail":
    if not x_google_access_token:
      raise HTTPException(status_code=401, detail="Missing Gmail access token")
    resp_text = handle_mail(user_text, x_google_access_token)
  elif intent == "calendar":
    resp_text = handle_calendar(user_text)
  elif intent == "health":
    resp_text = handle_health(user_text)
  else:
    intent = "general"
    resp_text = handle_general(user_text)

  return EchoOut(intent=intent, response=resp_text, email=x_user_email)
