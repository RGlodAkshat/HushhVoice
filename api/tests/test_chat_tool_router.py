from services.chat_tool_router import run_read_only_tool
from services.tool_router_service import ToolContext


def test_read_only_tool_blocked():
    ctx = ToolContext(
        user_id="u1",
        google_token=None,
        user_email=None,
        locale=None,
        timezone=None,
        request_id="req-1",
    )
    result = run_read_only_tool(
        tool_name="gmail_send",
        args={},
        ctx=ctx,
        turn_id="turn-1",
        step_index=1,
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "read_only_blocked"


def test_read_only_tool_requires_google():
    ctx = ToolContext(
        user_id="u1",
        google_token=None,
        user_email=None,
        locale=None,
        timezone=None,
        request_id="req-1",
    )
    result = run_read_only_tool(
        tool_name="gmail_search",
        args={"query": "from:test"},
        ctx=ctx,
        turn_id="turn-1",
        step_index=1,
    )
    assert result["ok"] is False
    assert result["data"]["code"] == "missing_google_token"
