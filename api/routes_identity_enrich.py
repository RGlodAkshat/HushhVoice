from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from flask import request

from app_context import OPENAI_MODEL, app, client, log
from json_helpers import jerror, jok


def _basic_name_parts(full_name: str) -> Dict[str, str]:
    parts = [p for p in full_name.split() if p]
    if not parts:
        return {"first": "", "last": "", "middle": ""}
    if len(parts) == 1:
        return {"first": parts[0], "last": "", "middle": ""}
    if len(parts) == 2:
        return {"first": parts[0], "last": parts[1], "middle": ""}
    return {"first": parts[0], "middle": " ".join(parts[1:-1]), "last": parts[-1]}


def _guess_phone_region(phone: str) -> str:
    # Minimal heuristic to avoid claiming real-world lookup.
    if phone.startswith("+1"):
        return "US/CA"
    if phone.startswith("+91"):
        return "IN"
    if phone.startswith("+44"):
        return "UK"
    if phone.startswith("+61"):
        return "AU"
    return "unknown"


def _offline_enrich(full_name: str, phone: str, email: str) -> Dict[str, Any]:
    name_parts = _basic_name_parts(full_name)
    email_domain = email.split("@")[-1] if "@" in email else ""
    region_guess = _guess_phone_region(phone)
    return {
        "summary": "Offline mode: inferred from provided input only.",
        "inferred_attributes": {
            "name_parts": name_parts,
            "email_domain": email_domain,
            "phone_region_guess": region_guess,
            "possible_locale": "unknown",
            "possible_timezones": [],
        },
        "possible_public_records": [],
        "questions_to_confirm": [
            "What country/timezone are you in?",
            "What organization are you affiliated with?",
        ],
        "confidence": 0.15,
    }


@app.post("/identity/enrich")
def identity_enrich():
    """
    Takes full_name, phone, email and returns a structured, non-lookup enrichment
    based only on the provided input. No external data sources are accessed.
    """
    data = request.get_json(force=True, silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()

    if not full_name or not phone or not email:
        return jerror("full_name, phone, and email are required.", 400)

    if "@" not in email:
        return jerror("Invalid email format.", 400)

    if not re.search(r"\d", phone):
        return jerror("Invalid phone format.", 400)

    if not client:
        return jok(_offline_enrich(full_name, phone, email))

    system = (
        "You are a privacy-first data assistant. "
        "Do NOT claim to have looked up or fetched any external data. "
        "Only infer from the provided inputs. "
        "Return JSON only, no extra text."
    )
    user = {
        "full_name": full_name,
        "phone": phone,
        "email": email,
    }

    schema = {
        "summary": "Short summary of what can be inferred from the inputs only.",
        "inferred_attributes": {
            "name_parts": {"first": "", "middle": "", "last": ""},
            "email_domain": "",
            "phone_region_guess": "",
            "possible_locale": "",
            "possible_timezones": [],
        },
        "possible_public_records": [],
        "questions_to_confirm": [],
        "confidence": 0.0,
    }

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "Given the inputs below, fill the JSON schema. "
                "Do not add fields. Do not include reasoning.\n\n"
                f"INPUTS:\n{json.dumps(user)}\n\n"
                f"SCHEMA:\n{json.dumps(schema)}"
            ),
        },
    ]

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.2,
            max_tokens=400,
        )
        content = (resp.choices[0].message.content or "").strip()
        enriched = json.loads(content)
        return jok(enriched)
    except Exception as e:
        log.exception("identity_enrich failed")
        fallback = _offline_enrich(full_name, phone, email)
        fallback["summary"] = "Fallback used due to model error."
        fallback["error"] = str(e)
        return jok(fallback)
