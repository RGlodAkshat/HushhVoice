# routes_onboarding_agent.py
# Flask routes module for Kai investor discovery (STRICT 8-question flow)
#
# ✅ Only asks: Intro + Q1..Q8 (no extra onboarding fields)
# ✅ Persistent memory (disk) so user can leave mid-way and resume
# ✅ Pinned state + next-question selection so it never “drifts”
# ✅ Tool relay endpoint for iOS: /onboarding/agent/tool
#
# Endpoints:
# - GET  /onboarding/agent/config?user_id=...
# - POST /onboarding/agent/token
# - POST /onboarding/agent/tool
# - GET  /onboarding/agent/state?user_id=...        (debug)
# - POST /onboarding/agent/reset                    (debug)
#
# Expected response envelope: jok(...) => { ok: true, data: ... }
#
# NOTE:
# - iOS should call /config on app open and after each memory_set tool call.
# - iOS should forward tool calls from Realtime (DataChannel) to /tool,
#   then send function_call_output back to the model.

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from flask import request

from app_context import OPENAI_API_KEY, app, client, log
from json_helpers import jerror, jok


# ============================================================
# Realtime + Fund Context
# ============================================================

REALTIME_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")

FUND_CONTEXT = {
    "fund_name": "Hushh Fund A",
    "tagline": "The AI-Powered Berkshire Hathaway",
    "one_liner": "AI-powered multi-strategy value investing designed for consistent, risk-adjusted alpha.",
    "share_classes": [
        {
            "class": "A",
            "name": "ULTRA",
            "unit_price_usd": 25_000_000,
            "notes": "Ultra High Net Worth tier with maximum allocation priority and exclusive benefits.",
        },
        {
            "class": "B",
            "name": "PREMIUM",
            "unit_price_usd": 5_000_000,
            "notes": "Premium tier with enhanced portfolio access and dedicated relationship management.",
        },
        {
            "class": "C",
            "name": "STANDARD",
            "unit_price_usd": 1_000_000,
            "notes": "Standard tier with full access to AI-powered multi-strategy alpha portfolio.",
        },
    ],
    "unit_explainer": "Units determine your allocation across share classes; you can invest in multiple classes.",
}

# ============================================================
# Strict flow (Intro + Q1..Q8)
# ============================================================

# Keys we store (ONLY these)
DISCOVERY_KEYS = [
    "net_worth",                    # Q1
    "asset_breakdown",              # Q1
    "investor_identity",            # Q2
    "capital_intent",               # Q3
    "allocation_comfort_12_24m",    # Q4
    "experience_proud",             # Q5
    "experience_regret",            # Q5
    "fund_fit_alignment",           # Q6
    "allocation_mechanics_depth",   # Q7
    "contact_country",              # Q8
]

# Ordered questions (the model must not deviate)
QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "Q1",
        "keys": ["net_worth", "asset_breakdown"],
        "text": (
            "Before we talk about investing, help me understand your financial base. "
            "Roughly speaking, what does your net worth look like, and how is it split — "
            "for example between cash, equities, businesses, real estate, or anything else?"
        ),
    },
    {
        "id": "Q2",
        "keys": ["investor_identity"],
        "text": (
            "How do you see yourself as an investor? "
            "For example — long-term value holder, opportunistic, conservative, aggressive, or something else?"
        ),
    },
    {
        "id": "Q3",
        "keys": ["capital_intent"],
        "text": (
            "When you invest, what’s your usual intent? "
            "Are you trying to grow wealth steadily, preserve capital, or meaningfully compound over the long term, "
            "even with short-term volatility?"
        ),
    },
    {
        "id": "Q4",
        "keys": ["allocation_comfort_12_24m"],
        "text": (
            "Thinking realistically — not aspirationally — how much capital would you be comfortable allocating "
            "to an opportunity like this over the next 12–24 months?"
        ),
    },
    {
        "id": "Q5",
        "keys": ["experience_proud", "experience_regret"],
        "text": (
            "What’s one investment decision you’re proud of — and one you’d handle differently today?"
        ),
    },
    {
        "id": "Q6",
        "keys": ["fund_fit_alignment"],
        "text": (
            "Based on what you’ve shared, here’s how Hushh Fund A works in one sentence: "
            "It’s an AI-driven, long-term value strategy designed to compound capital responsibly over time. "
            "Does that generally align with how you like to invest?"
        ),
    },
    {
        "id": "Q7",
        "keys": ["allocation_mechanics_depth"],
        "text": (
            "We offer three allocation tiers — Class A, B, and C — mainly differing by unit size and access level. "
            "Would you like me to walk you through them, or do you already have a preference?"
        ),
    },
    {
        "id": "Q8",
        "keys": ["contact_country"],
        "text": (
            "To wrap up, which country are you based in?"
        ),
    },
]

CLOSE_TEXT = (
    "That’s enough for now. Would you like me to summarize what I’ve understood, "
    "or should we continue later?"
)

COMPLETE_TEXT = (
    "Thanks — I have everything I need. I’ll show you a concise summary now."
)

INTRO_TEXT = (
    "Hi, I’m Kai, your financial AI assistant at Hushh. "
    "I help investors think clearly about capital allocation — not just fill forms. "
    "This will take about 3–4 minutes, you can answer freely, and you can skip anything you’re not comfortable with. "
    "I won’t ask for any bank or sensitive details. "
    "Quick context: Hushh Fund A is our AI-powered multi-strategy alpha fund — "
    f"“{FUND_CONTEXT['tagline']}”. Ready?"
)

# ============================================================
# State + persistence
# ============================================================

DEFAULT_STATE: Dict[str, Any] = {
    "agent": {"name": "Kai"},
    "created_at": None,
    "updated_at": None,
    "preferred_language": "English",  # we keep it stable; no auto language switching
    "fund_context": FUND_CONTEXT,
    "phase": "discovery",            # discovery -> close
    "last_question_id": None,        # "Q1"... "Q8"
    "discovery": {k: None for k in DISCOVERY_KEYS},
    "notes": [],
}

# In-memory cache (dev). Supabase (if enabled) is source of truth across restarts.
_STATE_BY_USER: Dict[str, Dict[str, Any]] = {}
_STATE_BY_USER_TS: Dict[str, float] = {}
_STATE_LOCK = Lock()

SUPABASE_URL = os.environ.get("HUSHHVOICE_URL_SUPABASE", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("HUSHHVOICE_SERVICE_ROLE_KEY_SUPABASE", "")
SUPABASE_ONBOARDING_TABLE = os.environ.get("HUSHHVOICE_ONBOARDING_TABLE_SUPABASE", "kai_onboarding_state")
SUPABASE_ONBOARDING_STATE_COLUMN = os.environ.get("HUSHHVOICE_ONBOARDING_STATE_COLUMN", "state")
SUPABASE_TIMEOUT_SECS = float(os.environ.get("HUSHHVOICE_SUPABASE_TIMEOUT_SECS", "5"))
STATE_CACHE_TTL_SECS = int(os.environ.get("HUSHH_ONBOARDING_CACHE_TTL", "5"))


def _now_iso() -> str:
    return datetime.now().isoformat()


def _state_dir() -> str:
    base = os.environ.get("HUSHH_ONBOARDING_STATE_DIR", "/tmp/hushh_onboarding_state")
    os.makedirs(base, exist_ok=True)
    return base


def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", user_id or "dev-anon")


def _state_path(user_id: str) -> str:
    return os.path.join(_state_dir(), f"{_safe_user_id(user_id)}.json")


def _supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _supabase_table_url() -> str:
    return f"{SUPABASE_URL}/rest/v1/{SUPABASE_ONBOARDING_TABLE}"


def _supabase_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _cache_get(user_id: str) -> Optional[Dict[str, Any]]:
    if STATE_CACHE_TTL_SECS <= 0:
        return None
    now = time.time()
    with _STATE_LOCK:
        ts = _STATE_BY_USER_TS.get(user_id)
        if not ts:
            return None
        if now - ts > STATE_CACHE_TTL_SECS:
            _STATE_BY_USER.pop(user_id, None)
            _STATE_BY_USER_TS.pop(user_id, None)
            return None
        return _STATE_BY_USER.get(user_id)


def _cache_set(user_id: str, st: Dict[str, Any]) -> None:
    if STATE_CACHE_TTL_SECS <= 0:
        return
    with _STATE_LOCK:
        _STATE_BY_USER[user_id] = st
        _STATE_BY_USER_TS[user_id] = time.time()


def _cache_clear(user_id: str) -> None:
    with _STATE_LOCK:
        _STATE_BY_USER.pop(user_id, None)
        _STATE_BY_USER_TS.pop(user_id, None)


def _load_state_from_supabase(user_id: str) -> Optional[Dict[str, Any]]:
    if not _supabase_enabled():
        return None
    url = f"{_supabase_table_url()}?user_id=eq.{quote(user_id, safe='')}&select={SUPABASE_ONBOARDING_STATE_COLUMN}"
    try:
        resp = requests.get(url, headers=_supabase_headers(), timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase load failed: %s", resp.text)
            return None
        rows = resp.json() or []
        if not rows:
            return None
        state = rows[0].get(SUPABASE_ONBOARDING_STATE_COLUMN)
        return state if isinstance(state, dict) else None
    except Exception:
        log.exception("Failed to load state from Supabase")
        return None


def _load_state_from_disk(user_id: str) -> Optional[Dict[str, Any]]:
    path = _state_path(user_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("Failed to load state from disk")
        return None


def _load_state(user_id: str) -> Optional[Dict[str, Any]]:
    cached = _cache_get(user_id)
    if cached is not None:
        return cached

    st = _load_state_from_supabase(user_id) if _supabase_enabled() else None
    if st is None:
        st = _load_state_from_disk(user_id)
    if st is not None:
        _cache_set(user_id, st)
    return st


def _save_state_to_supabase(user_id: str, st: Dict[str, Any]) -> bool:
    if not _supabase_enabled():
        log.info("[Onboarding] Supabase disabled; skipping save user_id=%s", user_id)
        return False
    url = _supabase_table_url()
    headers = _supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    payload = {"user_id": user_id, SUPABASE_ONBOARDING_STATE_COLUMN: st}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase save failed: status=%s body=%s", resp.status_code, resp.text)
            return False
        log.info("[Onboarding] Supabase save ok user_id=%s table=%s", user_id, SUPABASE_ONBOARDING_TABLE)
        return True
    except Exception:
        log.exception("Failed to save state to Supabase")
        return False


def _save_state_to_disk(user_id: str, st: Dict[str, Any]) -> None:
    path = _state_path(user_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("Failed to save state to disk")


def _save_state(user_id: str, st: Dict[str, Any]) -> None:
    _cache_set(user_id, st)
    if _save_state_to_supabase(user_id, st):
        return
    _save_state_to_disk(user_id, st)


def _delete_state_from_supabase(user_id: str) -> None:
    if not _supabase_enabled():
        return
    url = f"{_supabase_table_url()}?user_id=eq.{quote(user_id, safe='')}"
    headers = _supabase_headers()
    headers["Prefer"] = "return=minimal"
    try:
        resp = requests.delete(url, headers=headers, timeout=SUPABASE_TIMEOUT_SECS)
        if resp.status_code >= 400:
            log.warning("Supabase delete failed: %s", resp.text)
    except Exception:
        log.exception("Failed to delete state from Supabase")


def _deep_copy(obj: Any) -> Any:
    return json.loads(json.dumps(obj))


def _get_user_id() -> str:
    uid = request.args.get("user_id") or request.headers.get("X-User-Id")
    if uid:
        return uid.strip()
    data = request.get_json(force=True, silent=True) or {}
    uid = data.get("user_id")
    return (uid or "dev-anon").strip()


def _get_or_init_state(user_id: str) -> Dict[str, Any]:
    st = _load_state(user_id)
    if not st:
        st = _deep_copy(DEFAULT_STATE)
        st["created_at"] = _now_iso()
    st.setdefault("created_at", _now_iso())
    st["updated_at"] = _now_iso()

    # Ensure all keys exist (for forward compatibility)
    st.setdefault("discovery", {})
    for k in DISCOVERY_KEYS:
        st["discovery"].setdefault(k, None)
    st.setdefault("notes", [])
    st.setdefault("fund_context", FUND_CONTEXT)
    st.setdefault("preferred_language", "English")
    st.setdefault("phase", "discovery")
    st.setdefault("last_question_id", None)

    if not _missing_keys(st):
        st["phase"] = "complete"

    _cache_set(user_id, st)
    return st


def _is_filled(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, dict):
        return len(v) > 0
    return True


def _missing_keys(st: Dict[str, Any]) -> List[str]:
    disc = st.get("discovery", {})
    return [k for k in DISCOVERY_KEYS if not _is_filled(disc.get(k))]


def _next_question(st: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Picks the next question based on first missing key in the strict order.
    """
    missing = set(_missing_keys(st))
    for q in QUESTIONS:
        # If any key in this question is missing, ask it.
        if any(k in missing for k in q["keys"]):
            return q
    return None


def _append_note(st: Dict[str, Any], note: str) -> None:
    note = (note or "").strip()
    if not note:
        return
    st.setdefault("notes", [])
    st["notes"].append({"ts": _now_iso(), "note": note})


def _compact_state(st: Dict[str, Any]) -> Dict[str, Any]:
    is_complete = len(_missing_keys(st)) == 0
    completed_questions = _completed_questions_count(st)
    return {
        "phase": st.get("phase"),
        "last_question_id": st.get("last_question_id"),
        "preferred_language": st.get("preferred_language", "English"),
        "discovery": st.get("discovery", {}),
        "missing_keys": _missing_keys(st),
        "is_complete": is_complete,
        "completed_questions": completed_questions,
        "total_questions": len(QUESTIONS),
        "fund": {
            "fund_name": st["fund_context"]["fund_name"],
            "tagline": st["fund_context"]["tagline"],
            "share_classes": st["fund_context"]["share_classes"],
        },
        "notes_tail": (st.get("notes") or [])[-5:],
    }


def _completed_questions_count(st: Dict[str, Any]) -> int:
    disc = st.get("discovery", {})
    count = 0
    for q in QUESTIONS:
        if all(_is_filled(disc.get(k)) for k in q["keys"]):
            count += 1
    return count


# ============================================================
# Tools schema (ONLY what we need)
# ============================================================

TOOLS_SCHEMA = [
    {
        "type": "function",
        "name": "memory_set",
        "description": "Store answers to the fixed Kai onboarding questions. Use ONLY the allowed keys.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "patch": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "discovery": {
                            "type": "object",
                            "description": "Answers to the fixed discovery keys.",
                            "additionalProperties": False,
                            "properties": {k: {"type": "string"} for k in DISCOVERY_KEYS},
                        },
                        "last_question_id": {"type": "string", "description": "Q1..Q8"},
                        "phase": {"type": "string", "description": "discovery|close"},
                    },
                },
                "note": {"type": "string", "description": "Optional short note."},
            },
            "required": ["patch"],
        },
    },
    {
        "type": "function",
        "name": "memory_review",
        "description": "Return a short summary of what Kai has understood so far (for confirmation).",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "style": {"type": "string", "description": "short|bullet", "default": "short"}
            },
        },
    },
    {
        "type": "function",
        "name": "memory_get",
        "description": "Get the current memory snapshot (compact).",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
    },
]


# ============================================================
# Kai Instructions (Pinned Context + STRICT flow)
# ============================================================

def build_kai_instructions(st: Dict[str, Any]) -> str:
    fund = st["fund_context"]
    fund_lines = [
        f"{fund['fund_name']} — {fund['tagline']}",
        fund["one_liner"],
        "Share classes:",
    ]
    for c in fund["share_classes"]:
        fund_lines.append(f"- Class {c['class']} ({c['name']}): ${c['unit_price_usd']:,}/unit — {c['notes']}")
    fund_lines.append(fund["unit_explainer"])

    compact = _compact_state(st)
    next_q = _next_question(st)
    next_id = next_q["id"] if next_q else None

    # IMPORTANT: This prompt prohibits extra questions.
    # Kai must ask only the next missing question and then stop.
    return f"""
You are Kai — a premium financial AI assistant for Hushh.

LANGUAGE:
- Speak English by default.
- Do not switch languages unless the user explicitly asks.

SAFETY:
- Never ask for bank details, account numbers, routing numbers, SSN, or sensitive IDs.
- If user offers sensitive info, politely say you don’t need it and return to the flow.

STYLE:
- Sound human: calm, confident, unhurried.
- Ask ONE question at a time.
- Encourage longer answers.
- Do not overwhelm the user.
- Light compliment is allowed (brief, genuine, not excessive).

STRICT FLOW:
You are ONLY allowed to ask the following questions in order (no extra questions):
Q1..Q8. Do not ask any other questions.
Do not ask for city/zip/phone/etc. Do not ask for any other fields.

INTRO (use once at the beginning or when user returns after a break):
"{INTRO_TEXT}"

QUESTIONS (verbatim):
Q1: "{QUESTIONS[0]['text']}"
Q2: "{QUESTIONS[1]['text']}"
Q3: "{QUESTIONS[2]['text']}"
Q4: "{QUESTIONS[3]['text']}"
Q5: "{QUESTIONS[4]['text']}"
Q6: "{QUESTIONS[5]['text']}"
Q7: "{QUESTIONS[6]['text']}"
Q8: "{QUESTIONS[7]['text']}"

WHEN COMPLETE:
"{COMPLETE_TEXT}"

HOW TO USE MEMORY (MANDATORY):
- Your job is to ask ONLY the next missing question and then wait.
- After user answers, immediately call:
  memory_set(patch={{discovery:{{...}}, last_question_id:"<Q#>", phase:"discovery"}}, note:"optional")
- Fill only the relevant keys for that question. Do not fabricate.
- If all required fields are filled, say the completion line and stop (no further questions).
- If user says "continue later", do NOT ask new questions.
- If user asks for summary, call memory_review(style="short") and read it out, then stop.

FUND CONTEXT (consistent, short; only mention when needed or at Q6):
{chr(10).join(fund_lines)}

PINNED STATE (authoritative):
NextQuestionId = {json.dumps(next_id)}
Memory = {json.dumps(compact, ensure_ascii=False)}
""".strip()


def build_kickoff(st: Dict[str, Any]) -> Dict[str, Any]:
    """
    Kickoff should:
    - If Q1 missing -> intro + Q1
    - Else -> ask next missing question directly (no extra chatter)
    """
    next_q = _next_question(st)
    if not next_q:
        # All collected -> short completion line only
        instructions = (
            "We’re already good. Say this exactly and stop: "
            f"“{COMPLETE_TEXT}”"
        )
        return {
            "type": "response.create",
            "response": {"modalities": ["audio", "text"], "instructions": instructions},
        }

    if next_q["id"] == "Q1":
        instructions = (
            f"Say this intro (briefly): “{INTRO_TEXT}” "
            f"Then ask Q1 exactly: “{QUESTIONS[0]['text']}” "
            "Then wait."
        )
    else:
        instructions = (
            f"Ask {next_q['id']} exactly: “{next_q['text']}” "
            "Then wait."
        )

    return {
        "type": "response.create",
        "response": {"modalities": ["audio", "text"], "instructions": instructions},
    }


# ============================================================
# Routes
# ============================================================

@app.get("/onboarding/agent/config")
def onboarding_agent_config():
    user_id = _get_user_id()
    log.info("[Onboarding] config user_id=%s", user_id)
    st = _get_or_init_state(user_id)
    st["updated_at"] = _now_iso()
    _save_state(user_id, st)

    cfg = {
        "agent": {"name": "Kai"},
        "user_id": user_id,
        "realtime": {
            "model": REALTIME_MODEL,
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.6,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 700,
                "create_response": False,
                "interrupt_response": True,
            },
        },
        "tools": TOOLS_SCHEMA,
        "fund_context": FUND_CONTEXT,
        "instructions": build_kai_instructions(st),
        "state_compact": _compact_state(st),
        "missing_keys": _missing_keys(st),
        "is_complete": len(_missing_keys(st)) == 0,
        "next_question": (_next_question(st) or {}).get("id"),
        "next_question_text": (_next_question(st) or {}).get("text"),
        "completed_questions": _completed_questions_count(st),
        "total_questions": len(QUESTIONS),
        "kickoff": build_kickoff(st),
    }
    log.info("[Onboarding] config ok user_id=%s missing=%s next=%s", user_id, _missing_keys(st), cfg.get("next_question"))
    return jok(cfg)


@app.post("/onboarding/agent/token")
def onboarding_agent_token():
    """
    Creates ephemeral client_secret for WebRTC Realtime.
    iOS uses it as Bearer token to POST SDP to /v1/realtime/calls.
    """
    data = request.get_json(force=True, silent=True) or {}
    model = (data.get("model") or REALTIME_MODEL).strip()
    ttl_seconds = data.get("ttl_seconds")
    log.info("[Onboarding] token request model=%s ttl=%s", model, ttl_seconds)

    # SDK path if available
    try:
        if client and hasattr(client, "realtime") and hasattr(client.realtime, "sessions"):
            kwargs = {"model": model}
            if ttl_seconds:
                kwargs["ttl_seconds"] = int(ttl_seconds)
            sess = client.realtime.sessions.create(**kwargs)
            secret = getattr(getattr(sess, "client_secret", None), "value", None)
            if not secret:
                return jerror("Missing client_secret in realtime session response.", 500)
            log.info("[Onboarding] token ok model=%s sdk=1", model)
            return jok({"client_secret": secret, "model": model})
    except Exception:
        log.exception("SDK realtime.sessions.create failed; falling back to REST")

    # REST fallback
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {"model": model}
    if ttl_seconds:
        payload["ttl_seconds"] = int(ttl_seconds)

    try:
        resp = requests.post(
            "https://api.openai.com/v1/realtime/sessions",
            headers=headers,
            json=payload,
            timeout=20,
        )
        if resp.status_code >= 400:
            return jerror(resp.text, resp.status_code)

        out = resp.json() or {}
        secret = (out.get("client_secret") or {}).get("value")
        if not secret:
            return jerror("Missing client_secret in realtime session response.", 500)
        log.info("[Onboarding] token ok model=%s sdk=0", model)
        return jok({"client_secret": secret, "model": model})

    except Exception as e:
        log.exception("realtime session creation failed")
        return jerror(str(e), 500)


@app.post("/onboarding/agent/tool")
def onboarding_agent_tool():
    """
    iOS forwards tool calls here.
    Body:
      { user_id: "...", tool_name: "...", arguments: {...} }

    Returns:
      jok({ output: {...} })
    """
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()
    tool_name = (data.get("tool_name") or "").strip()
    args = data.get("arguments") or {}

    if not tool_name:
        return jerror("Missing tool_name", 400)

    st = _get_or_init_state(user_id)
    st["updated_at"] = _now_iso()
    log.info("[Onboarding] tool=%s user_id=%s supabase=%s", tool_name, user_id, _supabase_enabled())

    try:
        if tool_name == "memory_set":
            patch = args.get("patch") or {}
            note = (args.get("note") or "").strip()
            if not isinstance(patch, dict):
                return jerror("patch must be an object", 400)

            # Apply patch safely
            disc_patch = (patch.get("discovery") or {}) if isinstance(patch.get("discovery"), dict) else {}
            for k, v in disc_patch.items():
                if k not in st["discovery"]:
                    continue
                if isinstance(v, str):
                    st["discovery"][k] = v.strip()
                elif v is not None:
                    if isinstance(v, (dict, list)):
                        st["discovery"][k] = json.dumps(v, ensure_ascii=False)
                    else:
                        st["discovery"][k] = str(v)

            if isinstance(patch.get("last_question_id"), str):
                st["last_question_id"] = patch["last_question_id"].strip()

            if isinstance(patch.get("phase"), str):
                st["phase"] = patch["phase"].strip()

            if note:
                _append_note(st, note)

            missing = _missing_keys(st)
            if not missing:
                st["phase"] = "complete"
            elif st.get("phase") != "discovery":
                st["phase"] = "discovery"

            _save_state(user_id, st)

            nxt = _next_question(st)
            completed = _completed_questions_count(st)
            output = {
                "ok": True,
                "saved": True,
                "missing_keys": missing,
                "is_complete": len(missing) == 0,
                "next_question": (nxt or {}).get("id"),
                "completed_questions": completed,
                "total_questions": len(QUESTIONS),
            }
            return jok({"output": output})

        if tool_name == "memory_get":
            return jok({"output": _compact_state(st)})

        if tool_name == "memory_review":
            style = (args.get("style") or "short").strip()
            disc = st.get("discovery", {})

            if style == "bullet":
                summary = "\n".join([
                    f"- Net worth: {disc.get('net_worth') or '—'}",
                    f"- Asset breakdown: {disc.get('asset_breakdown') or '—'}",
                    f"- Investor identity: {disc.get('investor_identity') or '—'}",
                    f"- Capital intent: {disc.get('capital_intent') or '—'}",
                    f"- Allocation comfort (12–24m): {disc.get('allocation_comfort_12_24m') or '—'}",
                    f"- Experience (proud): {disc.get('experience_proud') or '—'}",
                    f"- Experience (regret): {disc.get('experience_regret') or '—'}",
                    f"- Fund fit: {disc.get('fund_fit_alignment') or '—'}",
                    f"- Allocation mechanics preference: {disc.get('allocation_mechanics_depth') or '—'}",
                    f"- Country: {disc.get('contact_country') or '—'}",
                ])
            else:
                summary = (
                    "Here’s what I’ve understood so far: "
                    f"your net worth and asset mix is {disc.get('net_worth') or 'not shared yet'} "
                    f"with {disc.get('asset_breakdown') or 'no breakdown yet'}. "
                    f"You see yourself as {disc.get('investor_identity') or '—'}, and your intent is {disc.get('capital_intent') or '—'}. "
                    f"Your comfortable allocation over 12–24 months is {disc.get('allocation_comfort_12_24m') or '—'}. "
                    f"Your proud decision: {disc.get('experience_proud') or '—'}; and what you’d redo: {disc.get('experience_regret') or '—'}. "
                    f"Fund fit: {disc.get('fund_fit_alignment') or '—'}. "
                    f"Country: {disc.get('contact_country') or '—'}. "
                    "If you want, we can refine any part."
                )

            return jok({"output": {"summary": summary, "missing_keys": _missing_keys(st), "next_question": (_next_question(st) or {}).get("id")}})

        return jerror(f"Unknown tool_name: {tool_name}", 400)

    except Exception as e:
        log.exception("onboarding_agent_tool failed")
        return jerror(str(e), 500)


@app.get("/onboarding/agent/state")
def onboarding_agent_state():
    """Debug endpoint to inspect state."""
    user_id = _get_user_id()
    st = _get_or_init_state(user_id)
    return jok({"user_id": user_id, "state": st, "missing_keys": _missing_keys(st), "next_question": (_next_question(st) or {}).get("id")})


@app.post("/onboarding/agent/reset")
def onboarding_agent_reset():
    """Dev helper: reset state for a user."""
    data = request.get_json(force=True, silent=True) or {}
    user_id = (data.get("user_id") or _get_user_id()).strip()

    _cache_clear(user_id)
    _delete_state_from_supabase(user_id)

    # Remove disk state too
    try:
        path = _state_path(user_id)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    st = _get_or_init_state(user_id)
    _save_state(user_id, st)
    return jok({"ok": True, "user_id": user_id, "state_compact": _compact_state(st)})
