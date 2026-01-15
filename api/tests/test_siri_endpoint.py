import sys
import types

from flask import Flask

if "openai" not in sys.modules:
    openai_mod = types.ModuleType("openai")

    class _OpenAI:
        def __init__(self, *args, **kwargs):
            pass

    openai_mod.OpenAI = _OpenAI
    sys.modules["openai"] = openai_mod

if "googleapiclient" not in sys.modules:
    googleapiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")

    def _build(*args, **kwargs):
        raise RuntimeError("googleapiclient.build should not be called in tests")

    discovery.build = _build
    googleapiclient.discovery = discovery
    sys.modules["googleapiclient"] = googleapiclient
    sys.modules["googleapiclient.discovery"] = discovery

if "google.oauth2.credentials" not in sys.modules:
    google_mod = types.ModuleType("google")
    oauth2_mod = types.ModuleType("google.oauth2")
    credentials_mod = types.ModuleType("google.oauth2.credentials")

    class _Credentials:
        pass

    credentials_mod.Credentials = _Credentials
    oauth2_mod.credentials = credentials_mod
    google_mod.oauth2 = oauth2_mod
    sys.modules["google"] = google_mod
    sys.modules["google.oauth2"] = oauth2_mod
    sys.modules["google.oauth2.credentials"] = credentials_mod

import routes.siri as siri_routes


def _make_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(siri_routes.siri_bp)
    app.config.update(TESTING=True)
    return app


def test_siri_missing_prompt_returns_error():
    client = _make_app().test_client()

    resp = client.post("/siri/ask", json={"tokens": {"app_jwt": "x"}})
    body = resp.get_json()

    assert resp.status_code == 400, "expected 400 when prompt is missing"
    assert body["ok"] is False, "expected ok=false for missing prompt"


def test_siri_missing_app_jwt_returns_unauthorized():
    client = _make_app().test_client()

    resp = client.post("/siri/ask", json={"prompt": "Hi"})
    body = resp.get_json()

    assert resp.status_code == 401, "expected 401 when app_jwt is missing"
    assert body["ok"] is False, "expected ok=false for missing app_jwt"


def test_siri_user_id_fallbacks(monkeypatch):
    client = _make_app().test_client()

    captured = {}

    def _fake_run_agentic_query(**kwargs):
        captured["user_id"] = kwargs.get("user_id")
        return {"speech": "ok", "display": "ok"}

    monkeypatch.setattr(siri_routes, "run_agentic_query", _fake_run_agentic_query)

    resp = client.post(
        "/siri/ask",
        json={"prompt": "Hi", "tokens": {"app_jwt": "x"}},
        headers={"X-User-Email": "u@example.com"},
    )
    body = resp.get_json()

    assert resp.status_code == 200, "expected 200 with valid prompt + app_jwt"
    assert body["ok"] is True, "expected ok=true on success"
    assert captured["user_id"] == "u@example.com", "expected fallback to X-User-Email when user_id missing"

    resp = client.post(
        "/siri/ask",
        json={"prompt": "Hi", "user_id": "u-body", "tokens": {"app_jwt": "x"}},
        headers={"X-User-Email": "u@example.com"},
    )
    assert resp.status_code == 200, "expected 200 with explicit user_id"
    assert captured["user_id"] == "u-body", "expected body user_id to override header fallback"
