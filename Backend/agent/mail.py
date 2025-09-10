from __future__ import annotations
from typing import List, Dict
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def fetch_last_messages(access_token: str, max_results: int = 20) -> List[Dict]:
    """
    Fetches the last N messages (From, Subject, Snippet) from Gmail using an OAuth access_token.
    Requires scope: https://www.googleapis.com/auth/gmail.readonly
    """
    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    results = service.users().messages().list(
        userId="me", labelIds=["INBOX"], maxResults=max_results
    ).execute()
    messages = results.get("messages", [])
    out: List[Dict] = []

    for m in messages:
        msg = service.users().messages().get(
            userId="me",
            id=m["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        out.append({
            "id": msg.get("id"),
            "threadId": msg.get("threadId"),
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
        })
    return out

def answer_from_mail_context(openai_client, messages: List[Dict], user_query: str) -> str:
    """
    Uses OpenAI to answer the user's mail request given a compact inbox context.
    """
    # Format concise context
    lines = []
    for i, m in enumerate(messages[:20], 1):
        lines.append(
            f"[{i}] From: {m['from']}\n"
            f"    Subject: {m['subject']}\n"
            f"    Date: {m['date']}\n"
            f"    Snippet: {m['snippet']}"
        )
    context = "\n\n".join(lines) if lines else "No recent messages."

    prompt = (
        "You are HushhVoice, an executive assistant with perfect email etiquette.\n"
        "You have the following inbox context:\n\n"
        f"{context}\n\n"
        "—\n"
        f"User request: {user_query}\n\n"
        "Instructions:\n"
        "- If asked to summarize, return a concise bullet list of key threads + actions.\n"
        "- If drafting a reply, produce a short, professional draft.\n"
        "- If the request cannot be completed from context, say precisely what’s missing.\n"
    )

    resp = openai_client.responses.create(
        model="gpt-4o",
        input=prompt,
        max_output_tokens=700,
    )
    return resp.output_text or "I couldn't generate a response."
