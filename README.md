# LITEngine — Legal Intelligence Terminal

A full-screen legal research chat for Indian case law. Ask in plain language or pick a tool from the `+` menu; LIT reads
the case, finds the closest judgments in a 505-judgment library, maps the argument, gives an indicative outcome
estimate for criminal appeals, and compares scenarios — each as an inline card with its sources and caveats.

| | |
|---|---|
| `lit-backend/` | FastAPI service (Hugging Face Docker Space): streaming agent, precedent search, extraction, argument graph, Juris (the outcome model) |
| `lit-frontend/` | React + Vite + TypeScript client (Vercel) |
| `docs/` | `ARCHITECTURE`, `PROTOCOL`, `MODEL_CARD`, `DEMO`, `RUNBOOK`, Phase 0 findings |
| `scripts/verify.sh` | One command for every check (there is no CI): `scripts/verify.sh [--fast] [--e2e]` |

**Try it without a backend:** run the frontend (`cd lit-frontend && npm install && npm run dev`) and open `/demo`, a
recorded run on a fictional matter. See `lit-frontend/README.md` and `lit-backend/README.md` for local setup, and
`CHANGELOG.md` for what 1.0.0 contains and what it does not.

The outcome estimate (Juris) is an indicative research aid, not legal advice; see `docs/MODEL_CARD.md` for what it is and is not.
