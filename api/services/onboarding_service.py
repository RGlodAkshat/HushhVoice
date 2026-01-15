from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

from clients.openai_client import client
from config import OPENAI_API_KEY, OPENAI_SUMMARY_MODEL, log
from storage.onboarding_state_store import (
    _cache_clear,
    _cache_set,
    _delete_state_from_disk,
    _delete_state_from_supabase,
    _load_state,
    _now_iso,
    _save_state,
    _save_state_to_supabase,
    _supabase_enabled,
)
from utils.errors import ServiceError


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
# ALL AGENT PROMPTS LIVE HERE (single place)
# ============================================================

AGENT_PROMPTS: Dict[str, Any] = {
    "intro_text": (
        "Hey — I’m Kai, your AI-powered financial agent at Hushh. "
        "My job is to understand you — how you think about money, risk, and long-term decisions — "
        "so I can actually be useful when it comes to financial advice and opportunities. "
        "Right now, I’m onboarding investors who are exploring HushhTech, "
        "so this is just a short, thoughtful conversation to get to know you properly. "
        "It’ll take about 3–4 minutes, you can answer in your own words, "
        "and you’re always free to skip anything you’re not comfortable sharing. "
        "Ready?"
    ),
    "close_text": (
        "That’s enough for now. Would you like me to summarize what I’ve understood, "
        "or should we continue later?"
    ),
    "complete_text": "Thanks — I have everything I need. I’ll show you a concise summary now.",
    "system_instructions_template": """
You are Kai — a human, thoughtful investor AI from Hushh.

This is NOT a form. This is a get-to-know-you conversation that happens to collect
a few important investing signals.

────────────────────────────────
HOW YOU SHOULD SOUND
────────────────────────────────
- Calm, curious, sharp, and human
- React briefly to interesting answers
- You may explore RELATED thoughts (background, motivations, stories)
- These side discussions must feel natural and short
- Always guide the conversation back to the main question

────────────────────────────────
RESPONSE SHAPE (AFTER EACH ANSWER)
────────────────────────────────
- Always respond in three parts:
  1) Acknowledge the user (1 short line)
  2) Reflect an insight (1–2 calm sentences, human tone)
  3) Gentle transition + ask the next question (ONE question only)
- Never rapid-fire questions or sound like a form
- Keep it brief; no long explanations

────────────────────────────────
NON-NEGOTIABLE RULES
────────────────────────────────
- You MUST collect answers for the fixed discovery questions Q1–Q8
- You MUST ask them in order
- You MUST ask only ONE core question at a time
- You MUST NOT invent or infer answers
- When an answer clearly satisfies the current question, store it using memory_set
- You MUST NOT introduce new data fields

────────────────────────────────
QUESTION INTENT (DO NOT CHANGE)
────────────────────────────────
Q1: Net worth & asset breakdown
Q2: Investor identity / style
Q3: Capital intent (growth vs preservation etc.)
Q4: Comfortable allocation in next 12–24 months
Q5: Investment proud of + investment regret
Q6: Alignment with Hushh’s philosophy
Q7: Allocation class understanding / preference
Q8: Country of residence

You may rephrase questions conversationally, but the intent must remain identical.

────────────────────────────────
INTRO (FIRST MESSAGE ONLY)
────────────────────────────────
"Hey, I’m Kai from Hushh. This isn’t a checklist — it’s a short investor conversation.
I’ll ask a few questions, we can riff a bit where it helps, and I’ll put together a clean
picture of how you think about investing. Ready?"

────────────────────────────────
WHEN FINISHED
────────────────────────────────
"That’s everything I need. I’ve got a solid understanding of your investing mindset now."

────────────────────────────────
STATE (INTERNAL — DO NOT SHOW USER)
────────────────────────────────
NextQuestionId = {next_question_id_json}
Memory = {memory_json}
""".strip(),
    "questions": [
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
            "text": "What’s one investment decision you’re proud of — and one you’d handle differently today?",
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
            "text": "To wrap up, which country are you based in?",
        },
    ],
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
QUESTIONS: List[Dict[str, Any]] = AGENT_PROMPTS["questions"]


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
    "last_answer": {"question_id": None, "patch": {}, "ts": None},
}


def _deep_copy(obj: Any) -> Any:
    return json.loads(json.dumps(obj))


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
        if any(k in missing for k in q["keys"]):
            return q
    return None


def _append_note(st: Dict[str, Any], note: str) -> None:
    note = (note or "").strip()
    if not note:
        return
    st.setdefault("notes", [])
    st["notes"].append({"ts": _now_iso(), "note": note})


def _completed_questions_count(st: Dict[str, Any]) -> int:
    disc = st.get("discovery", {})
    count = 0
    for q in QUESTIONS:
        if all(_is_filled(disc.get(k)) for k in q["keys"]):
            count += 1
    return count


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


def _highlight_fallback_summary(patch: Dict[str, Any]) -> str:
    labels = [
        ("net_worth", "Net worth"),
        ("asset_breakdown", "Asset breakdown"),
        ("investor_identity", "Investor identity"),
        ("capital_intent", "Capital intent"),
        ("allocation_comfort_12_24m", "Allocation comfort"),
        ("experience_proud", "Proud decision"),
        ("experience_regret", "Regret decision"),
        ("fund_fit_alignment", "Fund fit"),
        ("allocation_mechanics_depth", "Allocation mechanics"),
        ("contact_country", "Country"),
    ]
    parts = []
    for key, label in labels:
        val = (patch.get(key) or "").strip()
        if not val:
            continue
        parts.append(f"{label}: {val}")
        if len(parts) == 2:
            break
    if not parts:
        return ""
    return "Kai noted: " + " • ".join(parts)


def _highlight_summary(last_answer: Dict[str, Any]) -> str:
    patch = (last_answer or {}).get("patch") or {}
    fallback = _highlight_fallback_summary(patch)
    if not client:
        return fallback
    try:
        if not patch:
            return ""
        system = (
            "You are Kai's note-taker. Write 1–2 short, human sentences for a UI card called 'Kai Notes'. "
            "Summarize ONLY the most recent answer and add a light, thoughtful reflection. "
            "Be warm and conversational, under 240 characters, no bullets. "
            "If data is sparse, be brief and do not invent."
        )
        user = json.dumps(patch, ensure_ascii=False)
        resp = client.chat.completions.create(
            model=OPENAI_SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Latest answer data:\n{user}"},
            ],
            temperature=0.2,
            max_tokens=120,
        )
        content = (resp.choices[0].message.content or "").strip()
        return content or fallback
    except Exception:
        log.exception("Highlight summary generation failed")
        return fallback


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
            "properties": {"style": {"type": "string", "description": "short|bullet|highlight", "default": "short"}},
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
    compact = _compact_state(st)
    next_q = _next_question(st)
    next_id = next_q["id"] if next_q else None

    template: str = AGENT_PROMPTS["system_instructions_template"]
    return template.format(
        next_question_id_json=json.dumps(next_id),
        memory_json=json.dumps(compact, ensure_ascii=False),
    ).strip()


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
            f"“{AGENT_PROMPTS['complete_text']}”"
        )
        return {
            "type": "response.create",
            "response": {"modalities": ["audio", "text"], "instructions": instructions},
        }

    if next_q["id"] == "Q1":
        instructions = (
            f"Say this intro (briefly): “{AGENT_PROMPTS['intro_text']}” "
            f"Optionally add one friendly transition sentence, "
            f"then ask Q1 with the same intent as: “{QUESTIONS[0]['text']}”. "
            "Ask only ONE question. Then wait."
        )
    else:
        instructions = (
            "Briefly acknowledge the user in one natural sentence if appropriate, "
            f"then ask {next_q['id']} with the same intent as: “{next_q['text']}”. "
            "Ask only ONE question. Then wait."
        )

    return {
        "type": "response.create",
        "response": {"modalities": ["audio", "text"], "instructions": instructions},
    }


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
    st.setdefault("last_answer", {"question_id": None, "patch": {}, "ts": None})
    st.setdefault("fund_context", FUND_CONTEXT)
    st.setdefault("preferred_language", "English")
    st.setdefault("phase", "discovery")
    st.setdefault("last_question_id", None)

    if not _missing_keys(st):
        st["phase"] = "complete"

    _cache_set(user_id, st)
    return st


# ============================================================
# Service API
# ============================================================

def get_config(user_id: str) -> Dict[str, Any]:
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
    log.info(
        "[Onboarding] config ok user_id=%s missing=%s next=%s",
        user_id,
        _missing_keys(st),
        cfg.get("next_question"),
    )
    return cfg


def create_realtime_token(model: str, ttl_seconds: Optional[int]) -> Dict[str, Any]:
    # SDK path if available
    try:
        if client and hasattr(client, "realtime") and hasattr(client.realtime, "sessions"):
            kwargs = {"model": model}
            if ttl_seconds:
                kwargs["ttl_seconds"] = int(ttl_seconds)
            sess = client.realtime.sessions.create(**kwargs)
            secret = getattr(getattr(sess, "client_secret", None), "value", None)
            if not secret:
                raise ServiceError("Missing client_secret in realtime session response.", 500)
            log.info("[Onboarding] token ok model=%s sdk=1", model)
            return {"client_secret": secret, "model": model}
    except ServiceError:
        raise
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
            raise ServiceError(resp.text, resp.status_code)

        out = resp.json() or {}
        secret = (out.get("client_secret") or {}).get("value")
        if not secret:
            raise ServiceError("Missing client_secret in realtime session response.", 500)
        log.info("[Onboarding] token ok model=%s sdk=0", model)
        return {"client_secret": secret, "model": model}

    except ServiceError:
        raise
    except Exception as e:
        log.exception("realtime session creation failed")
        raise ServiceError(str(e), 500) from e


def handle_tool(user_id: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    st = _get_or_init_state(user_id)
    st["updated_at"] = _now_iso()
    log.info("[Onboarding] tool=%s user_id=%s supabase=%s", tool_name, user_id, _supabase_enabled())

    if tool_name == "memory_set":
        patch = args.get("patch") or {}
        note = (args.get("note") or "").strip()
        if not isinstance(patch, dict):
            raise ServiceError("patch must be an object", 400)

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

        if disc_patch:
            st["last_answer"] = {
                "question_id": st.get("last_question_id"),
                "patch": {k: str(v).strip() for k, v in disc_patch.items()},
                "ts": _now_iso(),
            }

        missing = _missing_keys(st)
        if not missing:
            st["phase"] = "complete"
        elif st.get("phase") != "discovery":
            st["phase"] = "discovery"

        _save_state(user_id, st)

        nxt = _next_question(st)
        completed = _completed_questions_count(st)
        return {
            "ok": True,
            "saved": True,
            "missing_keys": missing,
            "is_complete": len(missing) == 0,
            "next_question": (nxt or {}).get("id"),
            "next_question_text": (nxt or {}).get("text"),
            "last_question_id": st.get("last_question_id"),
            "completed_questions": completed,
            "total_questions": len(QUESTIONS),
        }

    if tool_name == "memory_get":
        return _compact_state(st)

    if tool_name == "memory_review":
        style = (args.get("style") or "short").strip()
        disc = st.get("discovery", {})

        if style == "highlight":
            summary = _highlight_summary(st.get("last_answer", {}))
            return {"summary": summary, "missing_keys": _missing_keys(st), "next_question": (_next_question(st) or {}).get("id")}

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

        return {"summary": summary, "missing_keys": _missing_keys(st), "next_question": (_next_question(st) or {}).get("id")}

    raise ServiceError(f"Unknown tool_name: {tool_name}", 400)


def get_state_debug(user_id: str) -> Dict[str, Any]:
    st = _get_or_init_state(user_id)
    return {"user_id": user_id, "state": st, "missing_keys": _missing_keys(st), "next_question": (_next_question(st) or {}).get("id")}


def sync_state(user_id: str, incoming_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not _supabase_enabled():
        raise ServiceError("Supabase not configured", 500)

    if isinstance(incoming_state, dict) and incoming_state:
        st = incoming_state
        st.setdefault("updated_at", _now_iso())
    else:
        st = _load_state(user_id) or _get_or_init_state(user_id)

    ok = _save_state_to_supabase(user_id, st)
    if not ok:
        raise ServiceError("Supabase sync failed", 500)
    return {"ok": True}


def reset_state(user_id: str) -> Dict[str, Any]:
    _cache_clear(user_id)
    _delete_state_from_supabase(user_id)
    _delete_state_from_disk(user_id, log_errors=False)

    st = _get_or_init_state(user_id)
    _save_state(user_id, st)
    return {"ok": True, "user_id": user_id, "state_compact": _compact_state(st)}
