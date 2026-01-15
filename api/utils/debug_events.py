from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

from config import DEBUG_CONSOLE_ENABLED, DEBUG_EVENTS_MAX

_LOCK = Lock()
_EVENTS: Deque[Dict[str, Any]] = deque(maxlen=DEBUG_EVENTS_MAX)
_COUNTER = 0


def debug_enabled() -> bool:
    return bool(DEBUG_CONSOLE_ENABLED)


def _next_id() -> int:
    global _COUNTER
    _COUNTER += 1
    return _COUNTER


def record_event(
    category: str,
    message: str,
    *,
    data: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    level: str = "info",
) -> Dict[str, Any]:
    if not debug_enabled():
        return {}
    event = {
        "id": _next_id(),
        "ts": time.time(),
        "level": level,
        "category": category,
        "message": message,
        "request_id": request_id or "",
        "data": data or {},
    }
    with _LOCK:
        _EVENTS.append(event)
    return event


def list_events(since_id: int = 0) -> List[Dict[str, Any]]:
    with _LOCK:
        if since_id <= 0:
            return list(_EVENTS)
        return [e for e in _EVENTS if e.get("id", 0) > since_id]


def clear_events() -> None:
    with _LOCK:
        _EVENTS.clear()
