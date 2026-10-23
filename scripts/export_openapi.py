"""
Write the app's OpenAPI document to disk (offline — no server needed).

    python scripts/export_openapi.py                 # writes openapi.json next to main.py
    python scripts/export_openapi.py --check         # exits 1 if the committed file is stale (drift test)

The frontend generates src/api/schema.d.ts from this file with `npm run gen:api`, so the wire types can never
silently drift from the pydantic models.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "openapi.json"


def render() -> str:
    from main import create_app

    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    fresh = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != fresh:
            sys.exit("openapi.json is stale — run `python scripts/export_openapi.py` and commit the result")
        print("openapi.json is up to date")
        return
    OUT.write_text(fresh, encoding="utf-8")
    print(f"wrote {OUT} ({len(fresh) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
