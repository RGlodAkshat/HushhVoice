from __future__ import annotations

import datetime as dt
from typing import Optional

import requests

from config import GOOGLE_CAL_BASE


# =========================
# Google helper calls (Calendar)
# =========================
def _google_get(access_token: str, path: str, params: dict):
    url = f"{GOOGLE_CAL_BASE}{path}"
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
        timeout=20,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Google GET {path} -> {r.status_code} {r.text}")
    return r.json()


def _google_post(access_token: str, path: str, json_body: dict):
    url = f"{GOOGLE_CAL_BASE}{path}"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=json_body,
        timeout=20,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Google POST {path} -> {r.status_code} {r.text}")
    return r.json()


def _iso(dt_obj: dt.datetime) -> str:
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
    return dt_obj.isoformat().replace("+00:00", "Z")


def _normalize_event_datetime(dt_str: str, tz: Optional[str] = None) -> str:
    """
    Normalize a datetime string coming from the LLM into a format
    that Google Calendar will accept as 'dateTime'.

    Rules:
      - If empty, raise.
      - If format is 'YYYY-MM-DDTHH:MM', append ':00'.
      - If it already has 'Z', '+' or '-' after the date, keep as-is.
      - If it has no explicit offset, that's fine; we'll pass a separate
        'timeZone' field in the event.
    """
    if not dt_str:
        raise ValueError("Empty datetime string")

    dt_str = dt_str.strip()

    # If we have a simple local datetime without seconds like '2025-12-06T10:30'
    if "T" in dt_str:
        date_part, time_part = dt_str.split("T", 1)
        # 'HH:MM' is length 5; add ':SS'
        if len(time_part) == 5:
            dt_str = f"{date_part}T{time_part}:00"

    # Look at everything after the date portion
    tail = dt_str[10:]
    # If there's already a Z or an explicit offset, keep it as-is
    if any(c in tail for c in ("Z", "+", "-")):
        return dt_str

    # No explicit offset: we rely on the separate 'timeZone' field.
    return dt_str
