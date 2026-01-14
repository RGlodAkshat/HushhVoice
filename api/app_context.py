from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from openai import OpenAI

# -------------------------------------------------------------------
# Path setup so we can import from backend/agents/*
# -------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))     # api/
ROOT_DIR = os.path.dirname(BASE_DIR)                      # project root
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# =========================
# Config & Initialization
# =========================
# Load root .env first, then backend/.env if present, then any CWD .env.
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))
load_dotenv()

APP_NAME = os.getenv("APP_NAME", "HushhVoice API")
APP_VERSION = os.getenv("APP_VERSION", "0.5.0")
PORT = int(os.getenv("PORT", "5050"))
DEBUG = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
OPENAI_SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4.1-nano")

# On serverless platforms, code dir is read-only. Use /tmp for writes.
DEFAULT_MEMORY = "/tmp/hushh_memory.json"
MEMORY_PATH = os.getenv("MEMORY_PATH", DEFAULT_MEMORY)
try:
    mem_dir = os.path.dirname(MEMORY_PATH) or "/tmp"
    os.makedirs(mem_dir, exist_ok=True)
except Exception:
    # Ignore dir creation errors; we'll no-op writes later if needed.
    pass

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "hushh_secret_🔥")
CORS(app, supports_credentials=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hushhvoice")

client: Optional[OpenAI] = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)

# === Optional: Google ID token verification (independent from Gmail access token) ===
VERIFY_GOOGLE_TOKEN = os.getenv("VERIFY_GOOGLE_TOKEN", "false").lower() in ("1", "true", "yes")
if VERIFY_GOOGLE_TOKEN:
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
    except Exception:
        VERIFY_GOOGLE_TOKEN = False  # graceful fallback
        id_token = None
        google_requests = None
else:
    id_token = None
    google_requests = None

GOOGLE_CAL_BASE = "https://www.googleapis.com/calendar/v3"
