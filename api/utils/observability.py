from __future__ import annotations

from typing import Any, Dict, Optional

from utils.debug_events import record_event


def log_event(
    category: str,
    message: str,
    *,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    request_id: Optional[str] = None,
    level: str = "info",
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = data or {}
    if session_id:
        payload["session_id"] = session_id
    if turn_id:
        payload["turn_id"] = turn_id
    return record_event(
        category,
        message,
        data=payload,
        request_id=request_id,
        level=level,
    )
