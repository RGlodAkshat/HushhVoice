from __future__ import annotations

from typing import Any, Dict, Optional

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover
    from dataclasses import dataclass

    @dataclass
    class BaseModel:  # type: ignore
        def dict(self, **kwargs):  # noqa: D401
            return self.__dict__

    def Field(default=None, **kwargs):  # type: ignore
        return default


class StreamEvent(BaseModel):
    event_id: str
    event_type: str
    ts: str
    session_id: str
    turn_id: Optional[str] = None
    message_id: Optional[str] = None
    seq: int = 0
    turn_seq: int = 0
    role: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
