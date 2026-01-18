import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from services.orchestrator_service import ConfirmationGate


def run():
    gate = ConfirmationGate()
    confirmation_id = gate.request_confirmation(
        turn_id="turn-1",
        action_type="send_email",
        preview={"to": "demo@example.com", "subject": "Hello"},
    )
    print("[confirmation_smoke] confirmation_id:", confirmation_id)


if __name__ == "__main__":
    run()
