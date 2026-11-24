"""
Run real agent flows (deterministic mode, real precedent library, real Juris model) and save the SSE event streams as
JSON fixtures for the frontend: reducer tests, card development and Playwright's mock server all consume these.

    python scripts/dump_fixtures.py        # writes ../lit-frontend/src/test/fixtures/*.json
"""

import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.update(PRECEDENT_ARTIFACT_DIR=str(ROOT / "data" / "precedent_artifacts" / "v1"), LLM_PROVIDER="none",
                  OMP_NUM_THREADS="1", TOKENIZERS_PARALLELISM="false", KMP_DUPLICATE_LIB_OK="TRUE")

from fastapi.testclient import TestClient  # noqa: E402

from main import create_app  # noqa: E402
from services.agent.workspace import sha256_text  # noqa: E402

OUT = ROOT.parent / "lit-frontend" / "src" / "test" / "fixtures"
CRIMINAL = (ROOT / "tests" / "fixtures" / "criminal_case.txt").read_text(encoding="utf-8")
CIVIL = (ROOT / "tests" / "fixtures" / "civil_case.txt").read_text(encoding="utf-8")
INPUTS = {"appellant_type": "accused_appeal", "filing_date": "2021-04-12"}


def parse(text):
    return [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith("data:")]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with TestClient(create_app()) as c:
        shas = {}
        for key, text in (("criminal", CRIMINAL), ("civil", CIVIL)):
            shas[key] = sha256_text(text)
            assert c.put(f"/api/v1/cases/{shas[key]}", json={"text": text}).status_code == 200

        def run(name, user, case="criminal", inputs=None, conv="fx", messages=None):
            body = {"client": {"version": "fixture", "schema_version": 1}, "conversation_id": conv, "run_id": "r_" + uuid.uuid4().hex[:8],
                    "messages": messages or [], "user_message": user,
                    "case": {"ref": shas[case], "title": "Fixture matter", "inputs": inputs or {}} if case else None}
            if not case:
                body.pop("case")
            events = parse(c.post("/api/v1/agent/chat", json=body).text)
            (OUT / f"{name}.json").write_text(json.dumps(events, indent=1), encoding="utf-8")
            print(f"{name:28} {len(events):3} events  {sorted({e['payload']['type'] for e in events if e['event'] == 'card'})}")
            return events

        paused = run("full_review_paused", {"text": "", "forced_tool": {"name": "full_review", "args": {}}}, conv="fx1")
        needs = next(e for e in paused if e["event"] == "needs_input")
        run("full_review_resumed", {"text": "", "input_response": {"card_id": needs["card_id"], "values": INPUTS, "pending": needs["payload"]["pending"]}}, conv="fx1")
        run("precedents", {"text": "", "forced_tool": {"name": "search_precedents", "args": {"query": "Section 302 murder, eleven hour delay in FIR, interested eyewitnesses"}}}, inputs={"filing_date": "2021-04-12"}, conv="fx2")
        run("argument_map", {"text": "", "forced_tool": {"name": "build_argument_map", "args": {}}}, conv="fx3")
        run("outcome", {"text": "", "forced_tool": {"name": "assess_outcome", "args": {}}}, inputs=INPUTS, conv="fx4")
        run("scenario", {"text": "What if the State were the appellant, and what if we added two supporting facts?"}, inputs=INPUTS, conv="fx5")
        run("ask", {"text": "What does the judgment say about the delay in lodging the FIR?"}, inputs=INPUTS, conv="fx6")
        run("out_of_scope", {"text": "", "forced_tool": {"name": "assess_outcome", "args": {}}}, case="civil", inputs=INPUTS, conv="fx7")
        run("help", {"text": "Hi, what can you do?"}, case=None, conv="fx8")
        (OUT / "matters.json").write_text(json.dumps({"criminal": shas["criminal"], "civil": shas["civil"]}), encoding="utf-8")


if __name__ == "__main__":
    main()
