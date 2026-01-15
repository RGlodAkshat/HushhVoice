from __future__ import annotations

import os
from typing import Dict, Optional

import requests


SUPABASE_URL = os.environ.get("HUSHHVOICE_URL_SUPABASE", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("HUSHHVOICE_SERVICE_ROLE_KEY_SUPABASE", "")
SUPABASE_TIMEOUT_SECS = float(os.environ.get("HUSHHVOICE_SUPABASE_TIMEOUT_SECS", "5"))


def supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def supabase_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def supabase_table_url(table_name: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table_name}"


def supabase_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = None):
    return requests.get(
        url,
        headers=headers or supabase_headers(),
        timeout=timeout or SUPABASE_TIMEOUT_SECS,
    )


def supabase_post(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[dict] = None,
    timeout: Optional[float] = None,
):
    return requests.post(
        url,
        headers=headers or supabase_headers(),
        json=json,
        timeout=timeout or SUPABASE_TIMEOUT_SECS,
    )


def supabase_delete(url: str, headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = None):
    return requests.delete(
        url,
        headers=headers or supabase_headers(),
        timeout=timeout or SUPABASE_TIMEOUT_SECS,
    )
