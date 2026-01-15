import json
import sys
import types
from types import SimpleNamespace

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

import services.tool_router_service as tool_router_service


class _StubCompletions:
    def __init__(self, responses):
        self._responses = responses
        self._idx = 0

    def create(self, **kwargs):
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


class _StubChat:
    def __init__(self, responses):
        self.completions = _StubCompletions(responses)


class _StubClient:
    def __init__(self, responses):
        self.chat = _StubChat(responses)


def test_tool_router_memory_tools(monkeypatch):
    calls = {}

    def _fake_search(user_id, query, limit):
        calls["search"] = (user_id, query, limit)
        return [{"id": "1", "content": "hi"}]

    def _fake_write(user_id, content, tags, source, sync):
        calls["write"] = (user_id, content, tags, source, sync)
        return {
            "id": "1",
            "content": content,
            "tags": tags or [],
            "created_at": "now",
            "source": source,
        }

    monkeypatch.setattr(tool_router_service, "search_memory", _fake_search)
    monkeypatch.setattr(tool_router_service, "write_memory", _fake_write)

    ctx = tool_router_service.ToolContext(
        user_id="u1",
        google_token=None,
        user_email=None,
        locale=None,
        timezone="UTC",
        request_id=None,
    )

    res = tool_router_service.TOOL_SPECS["memory_search"].handler({"query": "q", "limit": 2}, ctx)
    assert res["ok"] is True, "memory_search tool should return ok"
    assert calls["search"] == ("u1", "q", 2), "memory_search should pass correct args"

    res = tool_router_service.TOOL_SPECS["memory_write"].handler({"content": "note", "tags": ["t"]}, ctx)
    assert res["ok"] is True, "memory_write tool should return ok"
    assert calls["write"][0] == "u1", "memory_write should use ctx user_id"


def test_tool_router_requires_google_token():
    ctx = tool_router_service.ToolContext(
        user_id="u1",
        google_token=None,
        user_email=None,
        locale=None,
        timezone="UTC",
        request_id=None,
    )
    res = tool_router_service.TOOL_SPECS["gmail_search"].handler({"query": "from:me"}, ctx)
    assert res["ok"] is False, "gmail_search should fail without google token"
    assert res["error"]["code"] == "missing_google_token", "expected missing_google_token error"


def test_run_agentic_query_no_tools(monkeypatch):
    msg = SimpleNamespace(content="Hello there", tool_calls=None)
    resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    monkeypatch.setattr(tool_router_service, "client", _StubClient([resp]))

    out = tool_router_service.run_agentic_query(
        prompt="Hi",
        user_id="u1",
        google_token=None,
        user_email="u1@example.com",
        locale=None,
        timezone="UTC",
    )
    assert out["display"] == "Hello there", "expected direct model response when no tools"


def test_run_agentic_query_with_tool_call(monkeypatch):
    calls = {"search": 0}

    def _fake_search(user_id, query, limit):
        calls["search"] += 1
        return [{"id": "1", "content": "result"}]

    monkeypatch.setattr(tool_router_service, "search_memory", _fake_search)

    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="memory_search",
            arguments=json.dumps({"query": "q", "limit": 1}),
        ),
    )

    first_msg = SimpleNamespace(content=None, tool_calls=[tool_call])
    second_msg = SimpleNamespace(content="Done", tool_calls=None)
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=first_msg)]),
        SimpleNamespace(choices=[SimpleNamespace(message=second_msg)]),
    ]
    monkeypatch.setattr(tool_router_service, "client", _StubClient(responses))

    out = tool_router_service.run_agentic_query(
        prompt="Find q",
        user_id="u1",
        google_token=None,
        user_email="u1@example.com",
        locale=None,
        timezone="UTC",
    )
    assert calls["search"] == 1, "expected tool call to execute exactly once"
    assert out["display"] == "Done", "expected final response after tool execution"
