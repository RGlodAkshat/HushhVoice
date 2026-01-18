import os
import sys
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from services.chat_gateway import ChatGateway, SessionContext


def run():
    gateway = ChatGateway()
    ctx = SessionContext(session_id=str(uuid.uuid4()), user_id="test-user", request_id="req-123")
    event = {
        "event_type": "text.input",
        "payload": {"text": "hello"},
    }
    out = gateway.handle_event(event, ctx)
    print("[chat_gateway_unit] events:", len(out))
    for e in out:
        print("  ->", e.get("event_type"), e.get("payload"))


if __name__ == "__main__":
    run()
