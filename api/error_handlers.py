from __future__ import annotations

from app_context import app
from json_helpers import jerror


# =========================
# Error Handlers
# =========================
@app.errorhandler(404)
def not_found(_):
    return jerror("Route not found", 404, "not_found")


@app.errorhandler(500)
def internal(_):
    return jerror("Internal server error", 500, "internal_error")
