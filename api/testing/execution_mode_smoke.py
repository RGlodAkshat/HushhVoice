import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from services.orchestrator_service import ExecutionModeSelector


def run():
    selector = ExecutionModeSelector()
    mode = selector.choose(
        realtime_healthy=True,
        tool_count=2,
        has_write=True,
        ambiguity=False,
        long_running=False,
    )
    print("[execution_mode_smoke] pipeline=", mode.pipeline, "execution_mode=", mode.execution_mode)


if __name__ == "__main__":
    run()
