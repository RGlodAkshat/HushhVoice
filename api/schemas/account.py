from __future__ import annotations

from typing import List, Optional, TypedDict


class AccountDeleteRequest(TypedDict, total=False):
    user_id: Optional[str]
    apple_user_id: Optional[str]
    kai_user_id: Optional[str]


class AccountDeleteResponse(TypedDict, total=False):
    ok: bool
    user_ids: List[str]
