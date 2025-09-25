from typing import List, Dict



# ======================================================
# Gmail-powered endpoints (replace text-file based flow)
# ======================================================
def trim_email_fields(emails: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Ensure only safe, compact fields are forwarded to the model."""
    out = []
    for e in emails:
        out.append({
            "from": e.get("from", "")[:300],
            "subject": e.get("subject", "")[:300],
            "date": e.get("date", "")[:64],
            "snippet": e.get("snippet", "")[:1500],  # keep snippets compact
        })
    return out


def build_email_context(emails: List[Dict[str, str]], limit: int = 20, max_chars: int = 12000) -> str:
    """
    Build a compact, bounded context string for the LLM to reason over
    (keeps tokens under control).
    """
    block_lines = []
    total = 0
    for i, mail in enumerate(emails[:limit], start=1):
        block = (
            f"Email {i}:\n"
            f"From: {mail.get('from','')}\n"
            f"Subject: {mail.get('subject','')}\n"
            f"Date: {mail.get('date','')}\n"
            f"Snippet: {mail.get('snippet','')}\n"
        )
        total += len(block)
        if total > max_chars:
            break
        block_lines.append(block)
    return "\n".join(block_lines)