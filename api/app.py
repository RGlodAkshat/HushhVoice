from __future__ import annotations

import time
import uuid

from flask import Flask, g, request, got_request_exception
from flask_cors import CORS

from config import FLASK_SECRET
from utils.debug_events import debug_enabled, record_event
from utils.error_handlers import register_error_handlers


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = FLASK_SECRET
    CORS(app, supports_credentials=True)

    @app.before_request
    def _debug_request_start():
        rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        g.request_id = rid
        g.request_start_ts = time.time()
        if debug_enabled():
            record_event(
                "request",
                f"{request.method} {request.path} start",
                data={
                    "method": request.method,
                    "path": request.path,
                    "query": request.query_string.decode("utf-8") if request.query_string else "",
                },
                request_id=rid,
            )

    @app.after_request
    def _debug_request_end(response):
        rid = getattr(g, "request_id", None)
        start_ts = getattr(g, "request_start_ts", None)
        duration_ms = int((time.time() - start_ts) * 1000) if start_ts else None
        response.headers["X-Request-Id"] = rid or response.headers.get("X-Request-Id", "")
        if debug_enabled():
            record_event(
                "request",
                f"{request.method} {request.path} end",
                data={
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
                request_id=rid,
            )
        return response

    def _log_exception(sender, exception, **extra):
        if not debug_enabled():
            return
        record_event(
            "error",
            f"{type(exception).__name__}",
            data={"error": str(exception), "path": request.path},
            request_id=getattr(g, "request_id", None),
            level="error",
        )

    got_request_exception.connect(_log_exception, app)

    # Register blueprints
    from routes.onboarding import onboarding_bp
    from routes.profile import profile_bp
    from routes.account import account_bp
    from routes.siri import siri_bp
    from routes.tts import tts_bp
    from routes.mail import mail_bp
    from routes.calendar import calendar_bp
    from routes.meta import meta_bp
    from routes.echo import echo_bp
    from routes.intent import intent_bp
    from routes.identity_enrich import identity_enrich_bp
    from routes.debug import debug_bp

    app.register_blueprint(onboarding_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(siri_bp)
    app.register_blueprint(tts_bp)
    app.register_blueprint(mail_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(meta_bp)
    app.register_blueprint(echo_bp)
    app.register_blueprint(intent_bp)
    app.register_blueprint(identity_enrich_bp)
    app.register_blueprint(debug_bp)

    register_error_handlers(app)
    return app


app = create_app()
