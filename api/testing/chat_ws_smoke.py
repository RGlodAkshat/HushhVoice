import asyncio
import json
import uuid

import websockets


BASE_URL = "ws://127.0.0.1:5050/chat/stream"


async def run():
    session_id = str(uuid.uuid4())
    url = f"{BASE_URL}?session_id={session_id}"
    print(f"[chat_ws_smoke] connecting -> {url}")
    async with websockets.connect(url) as ws:
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "text.input",
            "ts": "2026-01-17T00:00:00Z",
            "session_id": session_id,
            "turn_id": None,
            "message_id": None,
            "seq": 1,
            "turn_seq": 0,
            "role": "user",
            "payload": {"text": "hello from smoke test"},
        }
        await ws.send(json.dumps(payload))
        for _ in range(4):
            msg = await ws.recv()
            print("[chat_ws_smoke] recv:", msg)


if __name__ == "__main__":
    asyncio.run(run())
