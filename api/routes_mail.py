from __future__ import annotations

from flask import request

from app_context import app, client, log
from auth_helpers import get_access_token_from_request
from json_helpers import jerror, jok
from mail_helpers import answer_from_mail
from openai_helpers import DEFAULT_SYSTEM, _coerce_messages, _ensure_system_first
from agents.email_assistant.gmail_fetcher import fetch_recent_emails, send_email
from agents.email_assistant.reply_helper import generate_reply_from_inbox


# =========================
# Mail Q&A (web)
# =========================
@app.post("/mailgpt/answer")
def mailgpt_answer():
    """
    One-shot: fetch last N emails and answer a natural-language question about them.
    Request body:
      {
        access_token?: string,          # or header X-Google-Access-Token
        query: string,
        max_results?: number (default 20),
        messages?: [ {role, content}, ... ]
      }
    Response:
      {
        answer: str,
        emails_used: int,
        relevant_indices: [int],
        emails_preview: [...]
      }
    """
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jerror("Missing 'query' in request body.", 400)

    access_token = get_access_token_from_request(data)
    if not access_token:
        return jerror(
            "Missing Gmail access token. Pass 'X-Google-Access-Token' header or 'access_token' in JSON.",
            401,
            "unauthorized",
        )

    max_results = int(data.get("max_results") or 20)
    incoming_messages = data.get("messages") or []

    try:
        result = answer_from_mail(
            access_token=access_token,
            query=query,
            max_results=max_results,
            incoming_messages=incoming_messages,
        )
        return jok(result)
    except Exception as e:
        log.exception("mailgpt_answer error")
        # Friendly, non-fatal fallback so web UI stays usable
        return jok({
            "answer": (
                "I couldn’t access your Gmail right now. "
                "Your token may be expired or misconfigured. Try reconnecting and asking again."
            ),
            "emails_used": 0,
            "relevant_indices": [],
            "emails_preview": [],
        })


# =========================
# Mail Reply (web)
# =========================
@app.post("/mailgpt/reply")
def mailgpt_reply():
    """
    Draft (and optionally send) a reply based on recent emails + instruction.
    Request body:
      {
        access_token?: string,
        instruction: string,
        max_results?: number (default 20),
        send?: bool (default false),
        messages?: [ {role, content}, ... ]
      }
    Response:
      { drafted: {to_email, subject, body}, sent?: bool }
    """
    data = request.get_json(force=True, silent=True) or {}
    instruction = (data.get("instruction") or "").strip()
    if not instruction:
        return jerror("Missing 'instruction' in request body.", 400)

    access_token = get_access_token_from_request(data)
    if not access_token:
        return jerror("Missing Gmail access token.", 401, "unauthorized")

    max_results = int(data.get("max_results") or 20)
    should_send = bool(data.get("send", False))

    try:
        inbox = fetch_recent_emails(access_token, max_results=max_results) or []
    except Exception as e:
        log.exception("gmail fetch in /mailgpt/reply failed")
        return jerror(f"Gmail fetch failed: {e}", 500)

    if not client:
        return jok({"drafted": {"to_email": "", "subject": "(offline)", "body": ""}, "sent": False})

    # Build prompt with memory window + task block (we keep your helper-based drafting for real content)
    incoming_messages = _coerce_messages(data.get("messages"))
    messages = _ensure_system_first(incoming_messages, DEFAULT_SYSTEM)

    user_name = request.headers.get("X-User-Name") or "Best regards,"
    drafted = generate_reply_from_inbox(inbox, instruction, user_name=user_name)
    if not drafted:
        return jerror("Could not generate a reply.", 500, "draft_failed")

    # Optionally send
    sent = False
    if should_send:
        to_email = drafted["to_email"]
        subject = drafted["subject"]
        body = drafted["body"]
        if not to_email or not subject or not body:
            return jerror("Draft missing fields. Not sending.", 400, "invalid_draft")
        try:
            sent = send_email(access_token, to_email, subject, body)
        except Exception as e:
            log.exception("send_email failed")
            return jerror(f"Send failed: {e}", 500, "send_failed")

    return jok({"drafted": drafted, "sent": sent})
