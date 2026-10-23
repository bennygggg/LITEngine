# The sample session

`/demo` replays a **real** run of LIT on a **fictional** matter ("Mohan Lal v. State of Rajasthan", an appeal against a
s.302 conviction). It needs no backend, so it works offline and on a cold Space. The banner says so, and every message
is tagged as recorded.

## How it works

`lit-backend/scripts/record_demo.py` drives the real agent (real precedent library, real outcome model, real LLM
narration) through a scripted nine-turn conversation and freezes each turn's event stream to
`lit-frontend/src/features/demo/recordings/lit-demo-v1.json`. The page feeds those events through the same
`reduceEvent` reducer and the same message and card components as a live run (`features/demo/useDemoPlayer.ts`), paced
by `replay.ts` (gaps capped, speed 1×/2×/4×). Nothing about the replay is mocked UI.

Turns: summary → argument map → outcome (pauses on the needs-input form, pre-filled with the recorded answer) →
precedents → scenarios → a question answered from the document with sources → a plain-words client explanation → an
off-topic request that is politely declined.

## Re-recording

LLM wording is not deterministic. Record a few times, read the transcript, and commit the best one.

```bash
cd lit-backend
export OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false KMP_DUPLICATE_LIB_OK=TRUE   # macOS only
.venv311/bin/python scripts/record_demo.py --verify     # needs HUGGINGFACE_API_KEY; uses the full local library
# review lit-backend/data/demo/transcript.md, then:
cd ../lit-frontend && npm test                          # validates the recording against the replay tests
```

`--verify` asserts: every event validates against the current schema; every expected card type is present, including a
sourced answer; there is exactly one needs-input moment; every citation in the text was issued by a tool that turn; the
outcome card carries its "Indicative" disclaimer; there are no run errors; each stream ends with `done` and no
warnings. It does not judge wording, so read the transcript yourself. `--verify-only --file <path>` re-checks a
recording without calling the model.

Re-record whenever any of these change: the card schema, the narration prompt (`PROMPT_VERSION`), the outcome model,
the precedent library, or the demo matter text (`tests/fixtures/demo_matter.txt` and `features/matters/samples.ts`).
Run `scripts/eval_agent.py` as well (20 prompts against the live model, hard checks such as "never infers appeal type").

## Presenting it

- **Presenter mode** (default): press **Send** to play each turn, so you control the pace. **Autoplay** plays on.
- Speed 1×/2×/4×, **Skip** finishes the current turn, **Restart** resets.
- On the form, the recorded answer is already selected; press **Continue**.
- **Run this live on the same matter** opens a real conversation on the same matter, so the audience can compare the
  replay with a live run. Live runs need the backend awake.
