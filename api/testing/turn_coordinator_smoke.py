import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from services.turn_coordinator import TurnCoordinator


def run():
    coord = TurnCoordinator()
    turn = coord.start_turn(
        user_id="test-user",
        thread_id=None,
        session_id="sess-1",
        input_mode="text",
        execution_mode="direct_response",
        pipeline="realtime",
        request_id="req-1",
    )
    coord.set_state(turn.turn_id, "thinking")
    coord.complete_turn(turn.turn_id, "success")
    print("[turn_coordinator_smoke] ok turn_id=", turn.turn_id)


if __name__ == "__main__":
    run()
