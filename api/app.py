from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from config import FLASK_SECRET
from utils.error_handlers import register_error_handlers


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = FLASK_SECRET
    CORS(app, supports_credentials=True)

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

    register_error_handlers(app)
    return app


app = create_app()
