from __future__ import annotations

from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

client: Optional[OpenAI] = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# OpenAI message assembly (short-term memory support)
# =========================
DEFAULT_SYSTEM = (
    "You are HushhVoice — a private, consent-first AI copilot. "
    "Use recent conversation history to resolve pronouns and ambiguity. "
    "Be concise, helpful, and ask for clarification only when truly needed."
)


def _normalize_message_role(m: dict) -> dict:
    role = m.get("role", "user")
    if role not in ("system", "user", "assistant"):
        role = "user"
    return {"role": role, "content": str(m.get("content", "")).strip()}


def _coerce_messages(messages: Any) -> List[Dict[str, str]]:
    """Coerce inbound messages array from the client into OpenAI chat format."""
    if not isinstance(messages, list):
        return []
    out: List[Dict[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        nm = _normalize_message_role(m)
        if nm["content"]:
            out.append(nm)
    return out


def _ensure_system_first(
    messages: List[Dict[str, str]],
    system_fallback: str = DEFAULT_SYSTEM,
) -> List[Dict[str, str]]:
    """Make sure there's a system prompt at the top."""
    if not messages:
        return [{"role": "system", "content": system_fallback}]
    if messages[0]["role"] != "system":
        return [{"role": "system", "content": system_fallback}] + messages
    # If there is a system but it's empty, replace it
    if not messages[0]["content"].strip():
        messages[0]["content"] = system_fallback
    return messages


def _append_task_block(
    messages: List[Dict[str, str]],
    block: str,
    as_user: bool = True,
) -> List[Dict[str, str]]:
    """Append a task-specific instruction/content block."""
    role = "user" if as_user else "assistant"
    if block and block.strip():
        messages.append({"role": role, "content": block.strip()})
    return messages


def _chat_complete(
    messages: List[Dict[str, str]],
    temperature: float = 0.6,
    max_tokens: int = 500,
) -> Dict[str, Any]:
    """Wrapper to call OpenAI chat with safety and offline fallback."""
    if not client:
        # Dev/offline fallback to show structure still works end-to-end
        joined = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-4:]])
        return {"offline": True, "content": f"(offline) {joined[-400:]}"}
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return {"offline": False, "content": (resp.choices[0].message.content or "").strip()}
