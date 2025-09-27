"""
Reply helper: Draft a full reply email using user instruction + last N emails as context.
Return shape:
{
  "to_email": str,
  "subject": str,
  "body": str
}
"""

from __future__ import annotations
import os, json, re
from typing import List, Dict, Optional
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# -----------------------------
# Utilities
# -----------------------------
def _safe(s: Optional[str]) -> str:
    return (s or "").strip()

def _email_only(addr: str) -> str:
    """Extract email from 'Name <email@x.com>'."""
    if not addr:
        return ""
    m = re.search(r"<([^>]+)>", addr)
    return (m.group(1) if m else addr).strip()

def _normalize_inbox(inbox: List[Dict], limit: int = 20) -> List[Dict]:
    """Simplify inbox objects for context."""
    out = []
    for m in inbox[:limit]:
        out.append({
            "from": _safe(m.get("from")),
            "from_email": _email_only(_safe(m.get("from_email") or m.get("from"))),
            "subject": _safe(m.get("subject")),
            "snippet": _safe(m.get("snippet")),
            "date": _safe(m.get("date")) or _safe(m.get("date_iso")),
        })
    return out

def _build_context_block(inbox: List[Dict]) -> str:
    """Produce a compact, numbered block to feed to the model."""
    lines = []
    for i, m in enumerate(inbox, 1):
        lines.append(
            f"Email {i}:\n"
            f"From: {m['from']}\n"
            f"FromEmail: {m['from_email']}\n"
            f"Subject: {m['subject']}\n"
            f"Date: {m['date']}\n"
            f"Snippet: {m['snippet']}\n"
        )
    return "\n".join(lines)


# -----------------------------
# Public API
# -----------------------------
def generate_reply_from_inbox(inbox: List[Dict], user_instruction: str, user_name: str = "Best regards,") -> Optional[Dict]:
    """
    Draft a reply email using GPT-4o, grounded in the last N emails + instruction.
    Returns dict with {to_email, subject, body} or None on failure.
    """
    if not client:
        return None

    inbox_n = _normalize_inbox(inbox, limit=20)
    context_block = _build_context_block(inbox_n)

    system_prompt = (
        "You are ReplyGPT. Draft a natural, professional email reply.\n"
        "- Use the user's instruction as the main guide.\n"
        "- You may use details from the provided recent emails for context, "
        "but it's not required if the instruction is self-contained.\n"
        "- Output STRICTLY valid JSON in this format:\n"
        "{\n"
        '  "to_email": "recipient@example.com",\n'
        '  "subject": "Subject line",\n'
        '  "body": "Full email body with greeting and closing, signed with the user\'s name."\n'
        "}\n"
        f"- Always sign the email with the user’s name: {user_name}\n"
    )

    user_prompt = (
        f"User Instruction:\n{user_instruction}\n\n"
        f"Recent Emails (for context):\n{context_block}\n\n"
        "Return only JSON. No prose, no code fences."
    )

    try:
        res = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=800,
        )
        raw = (res.choices[0].message.content or "").strip()
        obj = json.loads(raw)
        # basic validation
        if not isinstance(obj, dict):
            return None
        if not obj.get("to_email") or not obj.get("subject") or not obj.get("body"):
            return None
        return {
            "to_email": _safe(obj["to_email"]),
            "subject": _safe(obj["subject"]),
            "body": _safe(obj["body"]),
        }
    except Exception as e:
        print("⚠️ Reply draft error:", e)
        return None
