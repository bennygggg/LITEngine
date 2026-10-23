"""
Streaming behaviour that only shows over a real socket (TestClient buffers whole responses):
keep-alive pings during slow work, cancellation when the reader disconnects, and resume by Last-Event-ID.
"""

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from config import get_settings
from main import create_app
from services.agent.events import registry
from services.agent.workspace import sha256_text
from tests.helpers import CLIENT, case_text, chat_body

pytestmark = pytest.mark.live_server

TEXT = case_text()
SHA = sha256_text(TEXT)


@pytest.fixture(scope="module")
def server():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    cfg = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/health", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    httpx.put(f"{base}/api/v1/cases/{SHA}", json={"text": TEXT}, timeout=30).raise_for_status()
    yield base
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def fast_pings_and_slow_search(monkeypatch):
    monkeypatch.setattr(get_settings(), "AGENT_PING_S", 0.4)
    registry.clear()
    from services.agent import tools
    real = tools.search_library
    delay = {"s": 2.5}

    async def slow(*a, **k):
        await asyncio.sleep(delay["s"])
        return await real(*a, **k)

    monkeypatch.setattr(tools, "search_library", slow)
    yield delay


def open_stream(base, rid, last_event_id=None):
    """Each run id gets its own query so results are never served from the artifact cache (the 'slow' search must run)."""
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    body = chat_body({"text": "", "forced_tool": {"name": "search_precedents", "args": {"query": f"murder delay in FIR {rid}"}}}, SHA, run_id=rid)
    return httpx.stream("POST", base + "/api/v1/agent/chat", json=body, headers=headers, timeout=30)


def events_from(lines):
    for line in lines:
        if line.startswith("data:"):
            yield json.loads(line[5:].strip())


def test_pings_flow_while_a_slow_tool_runs_and_arrive_in_real_time(server):
    arrivals, events = [], []
    with open_stream(server, "r_ping") as r:
        for ev in events_from(r.iter_lines()):
            arrivals.append(time.monotonic()); events.append(ev)
            if ev["event"] == "done":
                break
    pings = [e for e in events if e["event"] == "ping"]
    assert len(pings) >= 3, [e["event"] for e in events]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(set(seqs))
    assert max(b - a for a, b in zip(arrivals, arrivals[1:])) < 1.2   # no long silence even though the tool took 2.5 s
    assert events[-1]["status"] == "complete"


def test_disconnect_cancels_the_run_after_the_grace_period(server, fast_pings_and_slow_search):
    fast_pings_and_slow_search["s"] = 30
    with open_stream(server, "r_cancel") as r:
        for ev in events_from(r.iter_lines()):
            if ev["event"] == "step":
                break                                   # tool is now sleeping; drop the connection
    time.sleep(2.5)                                     # AGENT_ORPHAN_CANCEL_S is 1 in tests
    log = registry.get("r_cancel")
    assert log is not None and log.finished
    last = json.loads(log._events[-1][2])
    assert last["event"] == "done" and last["status"] == "cancelled"


def test_stop_endpoint_cancels_immediately(server, fast_pings_and_slow_search):
    fast_pings_and_slow_search["s"] = 30
    with open_stream(server, "r_stop") as r:
        for ev in events_from(r.iter_lines()):
            if ev["event"] == "step":
                assert httpx.delete(f"{server}/api/v1/agent/runs/r_stop", timeout=5).json() == {"stopped": True}
            if ev["event"] == "done":
                assert ev["status"] == "cancelled"
                break


def test_reconnecting_with_last_event_id_resumes_the_same_run(server):
    first = []
    with open_stream(server, "r_resume") as r:
        for ev in events_from(r.iter_lines()):
            first.append(ev)
            if len(first) == 2:
                break                                   # drop after message_start + step start
    cut = first[-1]["seq"]
    rest = []
    with open_stream(server, "r_resume", last_event_id=cut) as r:
        for ev in events_from(r.iter_lines()):
            rest.append(ev)
            if ev["event"] == "done":
                break
    assert rest and all(e["seq"] > cut for e in rest)
    assert rest[-1]["event"] == "done" and rest[-1]["status"] == "complete"
    assert any(e["event"] == "card" for e in rest)       # the card produced after the drop still arrives
