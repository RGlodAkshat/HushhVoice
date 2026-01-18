from services.orchestrator_service import ExecutionModeSelector


def test_execution_mode_direct_when_simple():
    selector = ExecutionModeSelector()
    mode = selector.choose(
        realtime_healthy=True,
        tool_count=0,
        has_write=False,
        ambiguity=False,
        long_running=False,
    )
    assert mode.pipeline == "realtime"
    assert mode.execution_mode == "direct_response"


def test_execution_mode_orchestrated_when_write():
    selector = ExecutionModeSelector()
    mode = selector.choose(
        realtime_healthy=True,
        tool_count=1,
        has_write=True,
        ambiguity=False,
        long_running=False,
    )
    assert mode.execution_mode == "backend_orchestrated"
