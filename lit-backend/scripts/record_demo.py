"""
Record the sample session: drive the REAL agent (real precedent library, real outcome model, real LLM narration) through a
scripted conversation on the fictional demo matter and freeze every event stream to JSON for the frontend's replay.

    python scripts/record_demo.py              # records and writes lit-frontend/src/features/demo/recordings/lit-demo-v1.json
    python scripts/record_demo.py --verify     # also run the content checks (exit 1 if any fail)
    python scripts/record_demo.py --verify-only [--file path]

The replay renders through the same reducer as live streaming, so what is recorded here is exactly what a live run looks like.
LLM wording is not deterministic: record a few times, read data/demo/transcript.md, and commit the best one.
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PRECEDENT_ARTIFACT_DIR", str(ROOT / "data" / "precedent_artifacts" / "v1"))
for k, v in dict(OMP_NUM_THREADS="1", TOKENIZERS_PARALLELISM="false", KMP_DUPLICATE_LIB_OK="TRUE", LLM_PROVIDER="hf_router").items():
    os.environ.setdefault(k, v)

OUT = ROOT.parent / "lit-frontend" / "src" / "features" / "demo" / "recordings" / "lit-demo-v1.json"
TRANSCRIPT = ROOT / "data" / "demo" / "transcript.md"
MATTER = (ROOT / "tests" / "fixtures" / "demo_matter.txt").read_text(encoding="utf-8").strip()
MATTER_ID = "mohan-lal-302-rajasthan"
FILING_DATE = "2024-06-14"

TOOL_LABEL = {"build_argument_map": "Map the argument", "search_precedents": "Find precedents", "assess_outcome": "Assess the outcome",
              "run_scenario": "Explore scenarios", "extract_case_facts": "Read the case", "ask_case": "Ask about the case", "full_review": "Full case review"}

# (display text shown as the user's message, request, whether this turn attaches the matter)
SCRIPT: List[Dict[str, Any]] = [
    {"text": "Summarise this matter and tell me what is at stake.", "attach": True},
    {"forced_tool": {"name": "build_argument_map", "args": {}}},
    {"text": "How likely is the appeal to succeed?"},
    {"input": {"appellant_type": "accused_appeal", "filing_date": FILING_DATE}},   # answers the form the previous turn raised
    {"text": "Which authorities are closest on delay in lodging the FIR and reliance on interested eyewitnesses?"},
    {"text": "What if the State were the appellant, and what if we added two more supporting facts?"},
    {"text": "Does the judgment say anything about the recovery of the weapon?"},
    {"text": "Explain that estimate in plain words for a client who isn't a lawyer."},
    {"text": "What's the weather in Jaipur tomorrow?"},
]


def parse(text: str) -> List[Dict[str, Any]]:
    return [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith("data:")]


def display_for(step: Dict[str, Any]) -> str:
    if "input" in step:
        v = step["input"]
        who = {"accused_appeal": "Appeal by the accused", "state_appeal": "Appeal by the State or complainant"}.get(v["appellant_type"], "Appeal type not specified")
        d = datetime.fromisoformat(v["filing_date"]).strftime("%-d %b %Y")
        return f"{who} · filed {d}"
    if "forced_tool" in step:
        return TOOL_LABEL[step["forced_tool"]["name"]]
    return step["text"]


def record() -> Dict[str, Any]:
    from fastapi.testclient import TestClient
    from main import create_app
    from services.agent.orchestrator import orchestrator  # noqa: F401  (import side effects: models load)
    from services.agent.workspace import sha256_text

    sha = sha256_text(MATTER)
    turns: List[Dict[str, Any]] = []
    history: List[Dict[str, str]] = []
    inputs: Dict[str, Any] = {}
    pending_input = None
    with TestClient(create_app()) as c:
        assert c.put(f"/api/v1/cases/{sha}", json={"text": MATTER, "title": "Mohan Lal v. State of Rajasthan"}).status_code == 200
        status = c.get("/api/v1/agent/status").json()
        for i, step in enumerate(SCRIPT, 1):
            user: Dict[str, Any] = {"text": step.get("text", "")}
            if "forced_tool" in step:
                user["forced_tool"] = step["forced_tool"]
            if "input" in step:
                assert pending_input, "the form turn must come first"
                user["input_response"] = {"card_id": pending_input["card_id"], "values": step["input"], "pending": pending_input["payload"]["pending"]}
            body = {"client": {"version": "demo-recorder", "schema_version": 1}, "conversation_id": "demo", "run_id": f"demo-r{i}",
                    "messages": history[-12:], "user_message": user, "options": {"mode": "auto", "narrate": "llm"},
                    "case": {"ref": sha, "title": "Mohan Lal v. State of Rajasthan", "inputs": inputs}}
            resp = c.post("/api/v1/agent/chat", json=body)
            assert resp.status_code == 200, resp.text
            events = [e for e in parse(resp.text) if e["event"] != "ping"]
            for e in events:   # stable ids in the committed file
                e["v"] = 1
            pending_input = next((e for e in events if e["event"] == "needs_input"), None)
            meta = next((e for e in events if e["event"] == "meta"), None)
            if meta and meta.get("case_inputs"):
                inputs = {**inputs, **{k: v for k, v in meta["case_inputs"].items() if v}}
            if "input" in step:
                inputs = {**inputs, **step["input"]}
            text = "\n\n".join(e["delta"] for e in events if e["event"] == "text_delta")
            display = display_for(step)
            history += [{"role": "user", "content": display}] + ([{"role": "assistant", "content": text}] if text.strip() else [])
            turns.append({"user": {"text": display, "request": {"text": user["text"], "forced_tool": user.get("forced_tool"),
                                                              "input_response": user.get("input_response")}, "attach": bool(step.get("attach"))},
                          "events": events})
            kinds = [e["payload"]["type"] for e in events if e["event"] == "card"]
            print(f"turn {i}: {display[:58]:58} cards={kinds} done={events[-1]['status']} {events[-1]['timings']['total_ms']}ms")
    return {
        "meta": {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "schema_version": 1,
                 "server_version": status["server_version"], "llm": status["llm"], "library": status["library"],
                 "matter_id": MATTER_ID, "matter_sha": sha, "filing_date": FILING_DATE},
        "turns": turns,
    }


def verify(rec: Dict[str, Any]) -> List[str]:
    from pydantic import TypeAdapter
    from models.agent_schemas import AgentEvent

    ta = TypeAdapter(AgentEvent)
    problems: List[str] = []
    cards, issued, needs_input = set(), set(), 0
    for n, t in enumerate(rec["turns"], 1):
        evs = t["events"]
        issued_turn = set()
        for e in evs:
            try:
                ta.validate_python(e)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"turn {n}: event {e.get('event')} fails the schema: {str(exc)[:120]}")
            if e["event"] == "card":
                p = e["payload"]
                cards.add(p["type"])
                if p["type"] == "precedents":
                    issued_turn |= {h["ref"] for h in p["results"]}
                if p["type"] == "sources":
                    issued_turn |= {x["ref"] for x in p["excerpts"]}
                if p["type"] == "outcome" and not (p.get("disclaimer") and "Indicative" in p["disclaimer"]["text"]):
                    problems.append(f"turn {n}: outcome card lacks its disclaimer")
            if e["event"] == "needs_input":
                needs_input += 1
            if e["event"] == "error" and e["scope"] == "run":
                problems.append(f"turn {n}: run error {e['code']}")
        text = "".join(e["delta"] for e in evs if e["event"] == "text_delta")
        for ref in re.findall(r"\[([PS]\d{1,2})\]", text):
            if ref not in issued_turn:
                problems.append(f"turn {n}: citation [{ref}] was never issued")
        if evs[-1]["event"] != "done":
            problems.append(f"turn {n}: stream does not end with done")
        if evs[-1].get("warnings"):
            problems.append(f"turn {n}: warnings {evs[-1]['warnings']}")
    for needed in ("case_profile", "precedents", "argument_map", "outcome", "scenario", "sources"):
        if needed not in cards:
            problems.append(f"no {needed} card in the session")
    if needs_input != 1:
        problems.append(f"expected exactly one needs_input moment, found {needs_input}")
    return problems


def transcript(rec: Dict[str, Any]) -> str:
    lines = [f"# Demo transcript — recorded {rec['meta']['recorded_at']} · model {rec['meta']['llm'].get('narration_model')}\n"]
    for n, t in enumerate(rec["turns"], 1):
        lines.append(f"## {n}. {t['user']['text']}")
        for e in t["events"]:
            if e["event"] == "card":
                lines.append(f"- CARD {e['payload']['type']}: {e['payload']['title']}")
            elif e["event"] == "needs_input":
                lines.append("- NEEDS INPUT form")
            elif e["event"] == "step" and e["phase"] == "end":
                lines.append(f"- step {e['tool']} {e.get('status')} {e.get('duration_ms')}ms {e.get('summary') or ''}")
        parts: Dict[str, str] = {}
        for e in t["events"]:
            if e["event"] == "text_delta":
                parts[e["part_id"]] = parts.get(e["part_id"], "") + e["delta"]   # deltas of one part concatenate
        text = "\n\n".join(parts.values())
        if text:
            lines.append("\n> " + text.replace("\n", "\n> "))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--file", type=Path, default=OUT)
    args = ap.parse_args()
    if args.verify_only:
        rec = json.loads(args.file.read_text(encoding="utf-8"))
    else:
        rec = record()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
        TRANSCRIPT.write_text(transcript(rec), encoding="utf-8")
        print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB) and {TRANSCRIPT}")
    if args.verify or args.verify_only:
        problems = verify(rec)
        for p in problems:
            print("PROBLEM:", p)
        print("verify:", "OK" if not problems else f"{len(problems)} problem(s)")
        sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
