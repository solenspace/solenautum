from __future__ import annotations

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from autumn_sse_protocol import Done, SseError, SseEvent, TaskEnd, Token

MISSION = UUID("00000000-0000-0000-0000-000000000001")
TASK = UUID("00000000-0000-0000-0000-000000000002")


def test_token_validates() -> None:
    event = SseEvent.model_validate(
        {
            "type": "token",
            "content": "hello",
            "mission_id": str(MISSION),
            "task_id": str(TASK),
            "seq": 0,
        }
    )
    assert isinstance(event.root, Token)
    assert event.root.type == "token"


def test_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        SseEvent.model_validate(
            {
                "type": "fabricated",
                "content": "x",
                "mission_id": str(MISSION),
                "seq": 0,
            }
        )


def test_round_trip_json() -> None:
    raw = {
        "type": "task_end",
        "content": {"status": "succeeded", "latency_ms": 250},
        "mission_id": str(MISSION),
        "task_id": str(TASK),
        "seq": 7,
    }
    event = SseEvent.model_validate(raw)
    assert isinstance(event.root, TaskEnd)
    round_tripped = json.loads(event.model_dump_json())
    assert round_tripped["type"] == raw["type"]
    assert round_tripped["mission_id"] == raw["mission_id"]
    assert round_tripped["task_id"] == raw["task_id"]
    assert round_tripped["seq"] == raw["seq"]
    assert round_tripped["content"]["status"] == "succeeded"
    assert round_tripped["content"]["latency_ms"] == 250


def test_done_round_trip_preserves_cost_cents() -> None:
    raw = {
        "type": "done",
        "content": {"mission_status": "succeeded", "cost_cents": 42},
        "mission_id": str(MISSION),
        "seq": 99,
    }
    event = SseEvent.model_validate(raw)
    assert isinstance(event.root, Done)
    round_tripped = json.loads(event.model_dump_json())
    assert round_tripped["content"]["mission_status"] == "succeeded"
    assert round_tripped["content"]["cost_cents"] == 42
    assert round_tripped.get("task_id") is None


def test_error_round_trip_preserves_code() -> None:
    """Error code strings (e.g. resume_lost) must round-trip verbatim."""
    raw = {
        "type": "error",
        "content": {"code": "resume_lost", "message": "buffer evicted"},
        "mission_id": str(MISSION),
        "seq": 1,
    }
    event = SseEvent.model_validate(raw)
    assert isinstance(event.root, SseError)
    round_tripped = json.loads(event.model_dump_json())
    assert round_tripped["content"]["code"] == "resume_lost"
    assert round_tripped["content"]["message"] == "buffer evicted"


def test_rejects_negative_seq() -> None:
    with pytest.raises(ValidationError):
        SseEvent.model_validate(
            {
                "type": "token",
                "content": "hi",
                "mission_id": str(MISSION),
                "task_id": str(TASK),
                "seq": -1,
            }
        )
