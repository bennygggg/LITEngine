"""Shared helpers for agent tests."""

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLIENT = {"version": "test", "schema_version": 1}


def parse_sse(text: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def assert_stream_invariants(events: List[Dict[str, Any]]) -> None:
    """The ordering contract of the wire protocol (docs: plan §5.1)."""
    assert events, "empty stream"
    assert events[0]["event"] == "message_start", events[0]["event"]
    assert events[-1]["event"] == "done", events[-1]["event"]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(set(seqs)), f"seq not strictly increasing: {seqs}"
    open_steps: Dict[str, str] = {}
    for e in events:
        if e["event"] == "step":
            if e["phase"] == "start":
                open_steps[e["step_id"]] = e["tool"]
            elif e["phase"] == "end":
                assert e["step_id"] in open_steps, "step end without start"
                open_steps.pop(e["step_id"])
    assert not open_steps, f"steps never ended: {open_steps}"
    done_at = next(i for i, e in enumerate(events) if e["event"] == "done")
    assert not any(e["event"] == "text_delta" for e in events[done_at + 1:]), "text after done"


def case_text(name: str = "criminal_case.txt") -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def chat_body(user_message: Dict[str, Any], ref: Optional[str], inputs: Optional[Dict[str, Any]] = None,
              conversation_id: str = "c1", run_id: Optional[str] = None, messages: Optional[list] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "client": CLIENT, "conversation_id": conversation_id, "run_id": run_id or "r_" + uuid.uuid4().hex[:10],
        "messages": messages or [], "user_message": user_message,
    }
    if ref:
        body["case"] = {"ref": ref, "title": "Test matter", "inputs": inputs or {}}
    return body


def kinds(events: List[Dict[str, Any]], event: str = "card") -> List[str]:
    key = "payload"
    return [e[key]["type"] for e in events if e["event"] == event]
