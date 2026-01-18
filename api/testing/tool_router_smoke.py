import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from services.chat_tool_router import run_read_only_tool
from services.tool_router_service import ToolContext


def run():
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
    print("[tool_router_smoke] result:", result)


if __name__ == "__main__":
    run()
