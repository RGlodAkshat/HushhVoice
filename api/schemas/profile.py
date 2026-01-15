from __future__ import annotations

from typing import Any, Dict, Optional, TypedDict


class ProfilePayload(TypedDict, total=False):
    user_id: str
    full_name: str
    phone: str
    email: str


class ProfileResponse(TypedDict, total=False):
    exists: bool
    profile: Optional[Dict[str, Any]]
