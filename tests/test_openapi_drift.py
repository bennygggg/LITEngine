"""The committed openapi.json (source of the frontend's generated types) must match the live app."""

import json
from pathlib import Path

from main import create_app

OPENAPI = Path(__file__).resolve().parent.parent / "openapi.json"


def test_openapi_json_is_up_to_date():
    fresh = json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert OPENAPI.read_text(encoding="utf-8") == fresh, "run `python scripts/export_openapi.py` and commit the result"


def test_card_and_event_variants_are_in_the_contract():
    schemas = json.loads(OPENAPI.read_text(encoding="utf-8"))["components"]["schemas"]
    for name in ("CaseProfileCard", "PrecedentsCard", "ArgumentMapCard", "OutcomeCard", "ScenarioCard",
                 "SourcesCard", "NeedsInputCard", "DocumentCard", "ErrorCard", "CardEvent", "DoneEvent", "StepEvent"):
        assert name in schemas, name
