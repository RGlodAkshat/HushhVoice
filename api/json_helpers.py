from __future__ import annotations

import json
import os
import uuid
from typing import Any, Tuple

from flask import Response, jsonify, request


def jerror(message: str, status: int = 400, code: str = "bad_request") -> Tuple[Response, int]:
    rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    return jsonify({"ok": False, "error": {"code": code, "message": message}, "request_id": rid}), status


def jok(data: Any, status: int = 200) -> Tuple[Response, int]:
    rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    return jsonify({"ok": True, "data": data, "request_id": rid}), status


def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default
