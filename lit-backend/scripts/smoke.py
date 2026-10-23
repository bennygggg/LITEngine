"""
Post-deploy smoke test for a running LIT backend (staging or production).

    python scripts/smoke.py https://thebenmerlin-lit-backend.hf.space
    python scripts/smoke.py https://<private-space>.hf.space --token hf_xxx     # private Spaces need an Authorization header
    python scripts/smoke.py http://localhost:8000 --allow-fixture-index         # local run without the real library

Checks, in order: health, readiness (library loaded from the artifact, outcome model, embedder), registering the demo matter,
and a forced "Find precedents" run whose stream must satisfy the protocol invariants. The LLM is NOT required: the run
uses deterministic narration, so this works with LLM_PROVIDER=none and costs nothing. Exit code 0 only if every check passes.
"""

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

DEMO_MATTER = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "demo_matter.txt"
EXPECTED_DOCS = 505


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="server root, e.g. https://thebenmerlin-lit-backend.hf.space")
    ap.add_argument("--token", help="Hugging Face token (only for private Spaces)")
    ap.add_argument("--allow-fixture-index", action="store_true", help="do not fail when the 3-case fixture index is loaded")
    ap.add_argument("--wake-seconds", type=int, default=180, help="how long to wait for a sleeping Space")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    failures = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    with httpx.Client(headers=headers, timeout=httpx.Timeout(30.0, read=120.0)) as http:
        print(f"Smoke test: {base}")

        deadline = time.time() + args.wake_seconds
        health = None
        while time.time() < deadline:
            try:
                r = http.get(f"{base}/health")
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                    health = r.json()
                    break
            except httpx.HTTPError:
                pass
            time.sleep(3)
        check("health answers", bool(health and health.get("status") == "healthy"), f"version {health.get('version') if health else '?'}")
        if not health:
            return 1

        ready = http.get(f"{base}/api/v1/health/ready").json()
        index = ready.get("index", {})
        check("ready", bool(ready.get("ready")))
        check("outcome model loaded", bool(ready.get("outcome_model_loaded")))
        check("embedder ready", bool(ready.get("embedder_ready")))
        if args.allow_fixture_index:
            check("precedent library present", index.get("docs", 0) > 0, f"{index.get('source')}, {index.get('docs')} judgments")
        else:
            check("precedent library loaded from the artifact", index.get("source") == "artifact" and index.get("docs") == EXPECTED_DOCS,
                  f"{index.get('source')}, {index.get('docs')} judgments, version {index.get('version')}")
        llm = ready.get("llm", {})
        print(f"  info  LLM provider {llm.get('provider')} configured={llm.get('configured')}; agent_enabled={ready.get('agent_enabled')}")

        text = DEMO_MATTER.read_text(encoding="utf-8").strip()
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        put = http.put(f"{base}/api/v1/cases/{sha}", json={"text": text, "title": "Smoke test matter"})
        check("case registered", put.status_code == 200 and put.json().get("known") is True, f"{put.json().get('word_count') if put.status_code == 200 else put.status_code} words")

        body = {
            "client": {"version": "smoke", "schema_version": 1},
            "conversation_id": f"smoke-{uuid.uuid4().hex[:8]}",
            "run_id": f"smoke-{uuid.uuid4().hex[:12]}",
            "messages": [],
            "user_message": {"text": "", "forced_tool": {"name": "search_precedents", "args": {}}},
            "case": {"ref": sha, "title": "Smoke test matter", "inputs": {}},
            "options": {"mode": "deterministic", "narrate": "template"},
        }
        events, started = [], time.time()
        with http.stream("POST", f"{base}/api/v1/agent/chat", json=body) as resp:
            check("chat stream opens", resp.status_code == 200 and "text/event-stream" in resp.headers.get("content-type", ""), f"HTTP {resp.status_code}")
            if resp.status_code == 200:
                data = []
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].strip())
                    elif line == "" and data:
                        try:
                            events.append(json.loads("".join(data)))
                        except json.JSONDecodeError:
                            pass
                        data = []
        names = [e.get("event") for e in events if e.get("event") != "ping"]
        seqs = [e["seq"] for e in events if "seq" in e]
        check("first event is message_start, last is done", bool(names) and names[0] == "message_start" and names[-1] == "done")
        check("seq is strictly increasing", all(b > a for a, b in zip(seqs, seqs[1:])))
        done = next((e for e in events if e.get("event") == "done"), {})
        check("run completed", done.get("status") == "complete", f"{done.get('status')}, {int((time.time() - started) * 1000)} ms")
        cards = [e["payload"] for e in events if e.get("event") == "card"]
        precedents = next((c for c in cards if c.get("type") == "precedents"), None)
        check("a precedents card arrived with results", bool(precedents and precedents.get("results")),
              f"{len(precedents.get('results', [])) if precedents else 0} judgments")
        if precedents and precedents.get("results"):
            top = precedents["results"][0]
            print(f"  info  closest: {top.get('title', '')[:80]} (cosine {top.get('cosine')})")

    print("\nSMOKE " + ("PASSED" if not failures else f"FAILED: {', '.join(failures)}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
