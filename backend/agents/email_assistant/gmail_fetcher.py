# agents/email_assistant/gmail_fetcher.py
"""
Gmail fetch/send utilities (token-in, JSON-out).
- Accepts a short-lived OAuth ACCESS TOKEN (with gmail.readonly / gmail.send scopes).
- Fetches recent messages (efficient metadata mode).
- Normalizes headers and dates.
- Sends plain-text emails (optional CC/BCC/threading).

Designed for: last-20 style inbox QA + reply flows.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
import base64
import logging
import re

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


# =========================
# Service
# =========================
def build_service(access_token: str):
    """
    Build a Gmail API service using an OAuth ACCESS TOKEN (not an ID token).
    Required scopes:
      - gmail.readonly for fetch
      - gmail.send for send_email
    """
    if not access_token:
        raise ValueError("Missing Gmail access token")
    creds = Credentials(token=access_token)
    # 'cache_discovery=False' avoids a write attempt in serverless envs
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# =========================
# Helpers
# =========================
def _get_header(headers: List[Dict[str, str]], name: str) -> str:
    """Return first header value matching name (case-sensitive per Gmail)."""
    for h in headers or []:
        if h.get("name") == name:
            return h.get("value", "")
    return ""


_EMAIL_RE = re.compile(r"<([^>]+)>")

def _extract_email(addr: str) -> str:
    """Return the email part from 'Name <email@x.com>' if present."""
    m = _EMAIL_RE.search(addr or "")
    return (m.group(1) if m else addr or "").strip()


def _fmt_epoch_ms(ms: str) -> Tuple[str, str]:
    """
    Convert Gmail internalDate (ms as str) to:
      - ISO 8601 UTC (e.g., '2025-08-09T07:30:00Z')
      - human local-like 'YYYY-MM-DD HH:MM' (still UTC for determinism)
    """
    try:
        ts = int(ms) / 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z"), dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "", ""


def _trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[: n - 1] + "…")


# =========================
# Fetch
# =========================
def fetch_recent_emails(
    access_token: str,
    max_results: int = 20,
    q: Optional[str] = None,
    label_ids: Optional[List[str]] = None,
    include_snippet: bool = True,
) -> List[Dict[str, str]]:
    """
    Fetch up to `max_results` most recent messages (metadata only) for the signed-in user.

    Args:
        access_token: OAuth access token with gmail.readonly scope.
        max_results: how many messages to return (<= 100 is reasonable).
        q: optional Gmail search query (e.g., 'from:professor subject:assignment newer_than:7d').
        label_ids: optional label filters (e.g., ['INBOX', 'IMPORTANT']).
        include_snippet: include Gmail snippet in the response.

    Returns:
        List of dicts:
          {
            "id": str,
            "threadId": str,
            "from": str,          # "Name <email@x.com>" (trimmed)
            "from_email": str,    # "email@x.com" extracted
            "subject": str,
            "date": str,          # "YYYY-MM-DD HH:MM" (UTC)
            "date_iso": str,      # ISO 8601 UTC
            "snippet": str        # optional, trimmed
          }
    """
    service = build_service(access_token)

    # 1) List message IDs first (fast)
    try:
        list_kwargs = {
            "userId": "me",
            "maxResults": min(max(1, max_results), 100),
        }
        if q:
            list_kwargs["q"] = q
        if label_ids:
            list_kwargs["labelIds"] = label_ids

        resp = service.users().messages().list(**list_kwargs).execute()
        msg_ids = [m["id"] for m in (resp.get("messages") or [])]

        if not msg_ids:
            return []

        # 2) Fetch metadata for each message ID
        emails: List[Dict[str, str]] = []
        for mid in msg_ids:
            msg = service.users().messages().get(
                userId="me",
                id=mid,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date", "To", "Cc"],
            ).execute()

            payload = msg.get("payload", {})
            headers = payload.get("headers", [])
            internal_date = msg.get("internalDate", "")  # ms since epoch

            from_raw = _get_header(headers, "From")
            subject = _get_header(headers, "Subject") or "(No Subject)"

            date_iso, date_hhmm = _fmt_epoch_ms(internal_date)
            snippet = msg.get("snippet", "") if include_snippet else ""

            item = {
                "id": msg.get("id", ""),
                "threadId": msg.get("threadId", ""),
                "from": _trim(from_raw, 300),
                "from_email": _extract_email(from_raw),
                "subject": _trim(subject, 300),
                "date": date_hhmm,         # compact (UTC)
                "date_iso": date_iso,      # ISO 8601 (UTC)
                "snippet": _trim(snippet, 1500) if include_snippet else "",
            }
            emails.append(item)

        return emails

    except Exception as e:
        log.exception("Error fetching emails")
        # Surface a minimal, recoverable failure to caller
        raise RuntimeError(f"Gmail fetch error: {e}") from e


# =========================
# Send
# =========================
def _build_message(
    to_email: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Dict[str, str]:
    """
    Build a raw RFC 2822 message suitable for Gmail API send/insert.
    """
    if not to_email:
        raise ValueError("Missing 'to_email'")
    if not subject:
        raise ValueError("Missing 'subject'")
    if not body:
        raise ValueError("Missing 'body'")

    msg = MIMEText(body, _charset="utf-8")
    msg["to"] = to_email
    msg["subject"] = subject
    if cc:
        msg["cc"] = cc
    if bcc:
        msg["bcc"] = bcc

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    data = {"raw": raw}
    if thread_id:
        data["threadId"] = thread_id
    return data


def send_email(
    access_token: str,
    to_email: str,
    subject: str,
    body: str,
    *,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> bool:
    """
    Send a plain-text email via Gmail API.
    Requires scope: https://www.googleapis.com/auth/gmail.send
    """
    service = build_service(access_token)
    try:
        body_obj = _build_message(to_email, subject, body, cc=cc, bcc=bcc, thread_id=thread_id)
        result = service.users().messages().send(userId="me", body=body_obj).execute()
        log.info("Email sent: id=%s threadId=%s", result.get("id"), result.get("threadId"))
        return True
    except Exception as e:
        log.exception("Send failed")
        return False
