from services.turn_coordinator import TurnCoordinator


def test_turn_lifecycle_in_memory():
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
    assert turn.turn_id
    coord.set_state(turn.turn_id, "thinking")
    coord.complete_turn(turn.turn_id, "success")
