from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from clients.openai_client import client
from config import EMBED_MODEL, log
from storage.memory_store import (
    append_memory,
    load_memory,
    load_memory_from_supabase,
    save_memory,
    save_memory_to_supabase,
)
from storage.memory_store_v2 import create_memory


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _embed(text: str) -> Optional[List[float]]:
    if not client:
        return None
    try:
        resp = client.embeddings.create(model=EMBED_MODEL, input=text)
        return resp.data[0].embedding
    except Exception:
        log.exception("Embedding failed")
        return None


def _cosine_sim(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _normalize_tags(tags: Any) -> List[str]:
    if not tags:
        return []
    if isinstance(tags, list):
        out = []
        for t in tags:
            if isinstance(t, str) and t.strip():
                out.append(t.strip())
        return out
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    return []


def _ensure_local_memory(user_id: str) -> List[Dict[str, Any]]:
    entries = load_memory(user_id)
    if entries:
        return entries
    supa = load_memory_from_supabase(user_id)
    if supa:
        save_memory(user_id, supa)
        return supa
    return []


def search_memory(user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    if not user_id or not query:
        return []

    entries = _ensure_local_memory(user_id)
    if not entries:
        return []

    query_emb = _embed(query)
    updated = False
    scored: List[Dict[str, Any]] = []

    for e in entries:
        content = (e.get("content") or "").strip()
        if not content:
            continue
        emb = e.get("embedding")
        if emb is None and query_emb is not None:
            emb = _embed(content)
            if emb is not None:
                e["embedding"] = emb
                updated = True

        if query_emb is None or emb is None:
            score = 1.0 if query.lower() in content.lower() else 0.0
        else:
            score = _cosine_sim(query_emb, emb)

        scored.append({
            "id": e.get("id"),
            "content": content,
            "tags": e.get("tags") or [],
            "created_at": e.get("created_at"),
            "score": score,
        })

    if updated:
        save_memory(user_id, entries)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: max(1, limit)]


def write_memory(
    user_id: str,
    content: str,
    tags: Optional[List[str]] = None,
    source: Optional[str] = None,
    sync: bool = True,
) -> Dict[str, Any]:
    if not user_id or not content:
        raise ValueError("user_id and content are required")

    entry = {
        "id": str(uuid.uuid4()),
        "content": content.strip(),
        "tags": _normalize_tags(tags),
        "source": source or "agent",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "embedding": _embed(content) or None,
    }
    append_memory(user_id, entry)

    if sync:
        entries = load_memory(user_id)
        _ = save_memory_to_supabase(user_id, entries)
        _ = create_memory({
            "memory_id": entry["id"],
            "user_id": user_id,
            "type": "fact",
            "content": entry["content"],
            "source": entry["source"],
            "confidence": 0.85,
            "created_at": entry["created_at"],
            "updated_at": entry["updated_at"],
        })

    return {
        "id": entry["id"],
        "content": entry["content"],
        "tags": entry["tags"],
        "created_at": entry["created_at"],
        "source": entry["source"],
    }


def sync_memory_to_supabase(user_id: str) -> bool:
    entries = load_memory(user_id)
    if not entries:
        return False
    return save_memory_to_supabase(user_id, entries)
