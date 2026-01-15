from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class RealtimeTurnDetection(TypedDict, total=False):
    type: str
    threshold: float
    prefix_padding_ms: int
    silence_duration_ms: int
    create_response: bool
    interrupt_response: bool


class RealtimeConfig(TypedDict, total=False):
    model: str
    turn_detection: RealtimeTurnDetection


class OnboardingConfig(TypedDict, total=False):
    agent: Dict[str, Any]
    user_id: str
    realtime: RealtimeConfig
    tools: List[Dict[str, Any]]
    fund_context: Dict[str, Any]
    instructions: str
    state_compact: Dict[str, Any]
    missing_keys: List[str]
    is_complete: bool
    next_question: Optional[str]
    next_question_text: Optional[str]
    completed_questions: int
    total_questions: int
    kickoff: Dict[str, Any]


class ToolRequest(TypedDict, total=False):
    user_id: str
    tool_name: str
    arguments: Dict[str, Any]


class SyncRequest(TypedDict, total=False):
    user_id: str
    state: Dict[str, Any]
