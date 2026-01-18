from __future__ import annotations

from typing import Any, Dict, List


class RealtimeAdapter:
    """
    Placeholder adapter for vendor-specific realtime APIs.
    This will translate canonical events to provider events and back.
    """

    def __init__(self) -> None:
        self.connected = False

    def connect(self, session_id: str) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def send_event(self, event: Dict[str, Any]) -> None:
        _ = event

    def read_events(self) -> List[Dict[str, Any]]:
        return []
