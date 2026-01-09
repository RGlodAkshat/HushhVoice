from __future__ import annotations

import json
import os
import uuid

from flask import request

from app_context import app, log
from calendar_helpers import calendar_answer_core, calendar_plan_core
from google_helpers import _google_post, _normalize_event_datetime
from intent_helpers import classify_intent_text
from json_helpers import jerror, jok
from mail_helpers import answer_from_mail, draft_reply_from_mail
from openai_helpers import DEFAULT_SYSTEM, _chat_complete
from agents.email_assistant.gmail_fetcher import send_email


# =========================
# Siri: /siri/ask (iOS + Shortcuts)
# =========================
@app.post("/siri/ask")
def siri_ask():
    """
    Entry point for iOS App / App Intent "AskHushhVoice".

    Body:
      {
        "prompt": str,
        "locale"?: str,
        "timezone"?: str,
        "tokens"?: {
          "app_jwt"?: str,
          "google_access_token"?: str | null
        }
      }
    """
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jerror("Missing 'prompt'.", 400)

    # 1) App auth (your JWT) – placeholder
    app_jwt = (data.get("tokens", {}) or {}).get("app_jwt")
    if not app_jwt:
        return jerror("Missing app auth.", 401, "unauthorized")
    # TODO: verify app_jwt signature / expiry

    # 2) Optional Google token (enables mail/calendar intents)
    gtoken = (data.get("tokens", {}) or {}).get("google_access_token")

    user_email = request.headers.get("X-User-Email") or "siri@local"

    # Base messages for general chat
    messages = [
        {
            "role": "system",
            "content": (
                "You are HushhVoice — Siri channel. "
                "Respond briefly for speech. If the user asked about email or calendar "
                "but access is missing or broken, say so plainly and stop."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        # 3) Classify intent
        intent = classify_intent_text(prompt)
        log.info("[Siri] user=%s intent=%s", user_email, intent)

        # 4) If mail/calendar/health intents require Google and we don't have a token
        if intent in ("read_email", "send_email", "calendar_answer", "schedule_event") and not gtoken:
            msg = "I need Google access to do that. Open HushhVoice to connect Gmail and Calendar."
            return jok({"speech": msg, "display": msg})

        # 5) Intent-specific handling

        # --- Email summarize ---
        if intent == "read_email":
            try:
                result = answer_from_mail(
                    access_token=gtoken,
                    query=prompt,
                    max_results=20,
                    incoming_messages=None,
                )
                speech = result.get("answer") or "No answer."
                return jok({"speech": speech[:350], "display": speech})
            except Exception as e:
                log.exception("Siri read_email failed: %s", e)
                msg = "I hit an error reading your inbox. Please try again later."
                return jok({"speech": msg, "display": msg})

        # --- Email reply (draft + send) ---
        if intent == "send_email":
            try:
                user_name = request.headers.get("X-User-Name") or "Best regards,"
                # Optional flag from client; defaults to True
                send_now = bool(data.get("send_now", True))

                drafted = draft_reply_from_mail(
                    access_token=gtoken,
                    instruction=prompt,
                    user_name=user_name,
                    max_results=20,
                    incoming_messages=None,
                )
                to_email = drafted.get("to_email") or "(unknown)"
                subject = drafted.get("subject") or "(no subject)"
                body = drafted.get("body") or ""

                sent = False
                if send_now and to_email != "(unknown)":
                    try:
                        sent = send_email(gtoken, to_email, subject, body)
                    except Exception as e:
                        log.exception("Siri send_email send failed: %s", e)
                        sent = False

                if sent:
                    speech = f"Sent your email to {to_email} with subject: {subject}."
                    display = (
                        f"✅ **Email sent**\n\n"
                        f"- **To:** {to_email}\n"
                        f"- **Subject:** {subject}\n\n"
                        f"```text\n{body}\n```"
                    )
                else:
                    speech = f"Drafted an email to {to_email} with subject: {subject}."
                    display = (
                        f"**Draft preview**\n\n"
                        f"- **To:** {to_email}\n"
                        f"- **Subject:** {subject}\n\n"
                        f"```text\n{body}\n```"
                    )

                return jok({"speech": speech[:350], "display": display, "sent": sent})
            except Exception as e:
                log.exception("Siri send_email failed: %s", e)
                msg = "I couldn't send that email right now. Please try again in the app."
                return jok({"speech": msg, "display": msg})

        # --- Calendar summarize ---
        if intent == "calendar_answer":
            try:
                result = calendar_answer_core(
                    access_token=gtoken,
                    question=prompt,
                    time_min=None,
                    time_max=None,
                    max_results=50,
                    incoming_messages=None,
                )
                speech = result.get("answer") or "No events found."
                return jok({"speech": speech[:350], "display": speech})
            except Exception as e:
                log.exception("Siri calendar_answer failed: %s", e)
                msg = "I hit an error reading your calendar. Try again in a bit."
                return jok({"speech": msg, "display": msg})

                # --- Calendar scheduling (draft + create) ---
        if intent == "schedule_event":
            try:
                user_name = request.headers.get("X-User-Name") or ""

                # Optional timezone hint from iOS client
                req_tz = (data.get("timezone") or "").strip() or None
                default_tz = os.getenv("DEFAULT_TZ", "UTC")

                draft = calendar_plan_core(
                    access_token=gtoken,
                    instruction=prompt,
                    confirm=False,
                    default_dur=30,
                    user_name=user_name,
                    incoming_messages=None,
                )
                ev = draft.get("event", {}) or {}
                hs = draft.get("human_summary", "")

                if not ev:
                    msg = "I couldn’t draft that event."
                    return jok({"speech": msg, "display": msg})

                start_raw = ev.get("start") or ""
                end_raw = ev.get("end") or ""

                # 🔑 Always have a timezone: event → request → env → UTC
                tz = (
                    (ev.get("timezone") or "").strip()
                    or req_tz
                    or default_tz
                )

                if not start_raw or not end_raw:
                    raise RuntimeError(f"Parsed event missing start/end: {ev}")

                start_dt = _normalize_event_datetime(start_raw, tz)
                end_dt = _normalize_event_datetime(end_raw, tz)

                start_obj = {
                    "dateTime": start_dt,
                    "timeZone": tz,
                }
                end_obj = {
                    "dateTime": end_dt,
                    "timeZone": tz,
                }

                g_event: dict = {
                    "summary": ev.get("summary") or "(No title)",
                    "start": start_obj,
                    "end": end_obj,
                }
                if ev.get("location"):
                    g_event["location"] = ev["location"]
                if ev.get("description") or user_name:
                    desc = ev.get("description") or ""
                    if user_name:
                        desc = f"{desc}\n\n— {user_name}".strip()
                    g_event["description"] = desc
                if ev.get("attendees"):
                    g_event["attendees"] = [{"email": a} for a in ev["attendees"]]

                if ev.get("conference"):
                    g_event["conferenceData"] = {
                        "createRequest": {
                            "requestId": str(uuid.uuid4()),
                            "conferenceSolutionKey": {"type": "hangoutsMeet"},
                        }
                    }

                created = _google_post(
                    gtoken,
                    "/calendars/primary/events?conferenceDataVersion=1",
                    g_event,
                )

                speech = f"Scheduled {ev.get('summary', '(no title)')} at {start_dt}."
                display = hs or speech

                return jok({
                    "speech": speech[:300],
                    "display": display,
                    "event_id": created.get("id"),
                    "event_link": created.get("htmlLink"),
                })
            except Exception as e:
                log.exception("Siri schedule_event failed: %s", e)
                # Dev-friendly: keep speech user-facing, show error in display for debugging
                speech = "I hit an error scheduling that event. Please try again later."
                display = f"{speech}\n\n[debug] {e}"
                return jok({"speech": speech, "display": display})


        # --- Health placeholder ---
        if intent == "health":
            msg = (
                "Health integration is still in preview. "
                "Use the HushhVoice app or web to pair a supported device."
            )
            return jok({"speech": msg, "display": msg})

        # --- General chat fallback ---
        out = _chat_complete(messages, temperature=0.5, max_tokens=240)
        text = out["content"] or "Sorry, I didn’t catch that."
        return jok({"speech": text[:350], "display": text})

    except Exception as e:
        log.exception("Siri ask failed")
        msg = "I ran into an error answering that. Please try again in a bit."
        return jok({"speech": msg, "display": msg})
