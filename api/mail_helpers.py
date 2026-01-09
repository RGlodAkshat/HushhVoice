from __future__ import annotations

from typing import Any, Dict, List, Optional

from app_context import client, log
from agents.email_assistant.gmail_fetcher import fetch_recent_emails, send_email
from agents.email_assistant.reply_helper import generate_reply_from_inbox
from agents.email_assistant.helper_functions import build_email_context, trim_email_fields

from openai_helpers import (
    DEFAULT_SYSTEM,
    _append_task_block,
    _chat_complete,
    _coerce_messages,
    _ensure_system_first,
)


# =========================
# Shared helpers for mail
# =========================
def answer_from_mail(
    access_token: str,
    query: str,
    max_results: int = 20,
    incoming_messages: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Shared email QA core:
      - fetch recent emails via Gmail
      - trim fields
      - build LLM prompt
      - call OpenAI
    Returns a dict like /mailgpt/answer would return.
    Raises RuntimeError on hard failure.
    """
    if not access_token:
        raise RuntimeError("Missing Gmail access token")

    # 1) Fetch emails from Gmail
    try:
        emails = fetch_recent_emails(access_token, max_results=max_results) or []
    except Exception as e:
        log.exception("gmail fetch in answer_from_mail failed")
        raise RuntimeError(f"Gmail fetch failed: {e}") from e

    emails_trimmed = trim_email_fields(emails)
    context = build_email_context(emails_trimmed, limit=max_results)

    # 2) Offline / no-OpenAI fallback
    if not client:
        preview = emails_trimmed[:5]
        return {
            "answer": f"(offline) You asked: {query}. I fetched {len(emails)} emails.",
            "emails_used": len(emails_trimmed),
            "relevant_indices": [],
            "emails_preview": preview,
        }

    # 3) Build messages with memory + task block
    base_messages = _coerce_messages(incoming_messages) if incoming_messages else []
    messages = _ensure_system_first(base_messages, DEFAULT_SYSTEM)

    system_prompt = (
        "You are a personal inbox analyst. "
        "Use ONLY the provided email context and general knowledge to answer. "
        "Summarize clearly, highlight urgent/important items, and say if unsure."
    )
    messages.append({"role": "system", "content": system_prompt})

    user_block = (
        f"User Query:\n{query}\n\n"
        f"Recent Emails (most recent first):\n{context}\n\n"
        "Return a helpful answer in plain text. "
        "If you cite specific emails, reference key details."
    )
    messages = _append_task_block(messages, user_block, as_user=True)

    # 4) Call OpenAI
    out = _chat_complete(messages, temperature=0.4, max_tokens=1000)
    answer = out["content"]

    # 5) Optional parse of "Relevant: [..]" if present
    import re
    rel = re.findall(r"Relevant:\s*\[([0-9,\s]+)\]", answer or "")
    relevant_indices: List[int] = []
    if rel:
        try:
            relevant_indices = [
                int(x.strip()) for x in rel[0].split(",") if x.strip().isdigit()
            ]
        except Exception:
            relevant_indices = []

    return {
        "answer": answer,
        "emails_used": len(emails_trimmed),
        "relevant_indices": relevant_indices,
        "emails_preview": emails_trimmed[: min(5, len(emails_trimmed))],
    }


def draft_reply_from_mail(
    access_token: str,
    instruction: str,
    user_name: str,
    max_results: int = 20,
    incoming_messages: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Shared email reply drafting core:
      - fetch recent inbox
      - use generate_reply_from_inbox(...)
    Returns dict {to_email, subject, body}.
    """
    if not access_token:
        raise RuntimeError("Missing Gmail access token")
    if not instruction.strip():
        raise RuntimeError("Missing instruction for reply")

    try:
        inbox = fetch_recent_emails(access_token, max_results=max_results) or []
    except Exception as e:
        log.exception("gmail fetch in draft_reply_from_mail failed")
        raise RuntimeError(f"Gmail fetch failed: {e}") from e

    drafted = generate_reply_from_inbox(inbox, instruction, user_name=user_name)
    if not drafted:
        raise RuntimeError("Could not generate a reply draft")

    return drafted
