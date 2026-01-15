from __future__ import annotations

from flask import Flask

from utils.json_helpers import jerror


# =========================
# Error Handlers
# =========================
def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_):
        return jerror("Route not found", 404, "not_found")

    @app.errorhandler(500)
    def internal(_):
        return jerror("Internal server error", 500, "internal_error")
