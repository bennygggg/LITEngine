"""
Packaging guard for Juris.

Hugging Face Spaces reject binary files in git, so the model artifact (`juris.joblib`) is NOT committed: it is published to the private
dataset repo and the Space downloads it at start. What IS committed is `model_card.json`, whose `artifact_sha256` pins exactly which
file the app may load. These tests keep that arrangement from silently breaking.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import juris

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
ARTIFACT = Path("data") / "juris" / "model" / "juris.joblib"
CARD = Path("data") / "juris" / "model" / "model_card.json"


def _lines(path: Path) -> list:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def test_default_artifact_path_is_the_published_one():
    assert juris.DEFAULT_MODEL_PATH == BACKEND / ARTIFACT
    assert "outcome_classifier_binary" not in str(juris.MODEL_PATH) and "outcome_dataset" not in str(juris.MODEL_PATH)


def test_the_card_is_committed_and_pins_the_artifact_hash():
    card = json.loads((BACKEND / CARD).read_text(encoding="utf-8"))
    assert len(card["artifact_sha256"]) == 64 and card["artifact"] == "juris.joblib"
    if (BACKEND / ARTIFACT).exists():       # present on a dev machine; fetched on first start elsewhere
        assert hashlib.sha256((BACKEND / ARTIFACT).read_bytes()).hexdigest() == card["artifact_sha256"]


def test_the_binary_stays_out_of_git_and_the_image_but_the_card_goes_in():
    docker = _lines(BACKEND / ".dockerignore")
    assert f"!{CARD.as_posix()}" in docker and f"!{ARTIFACT.as_posix()}" not in docker
    assert "!data/juris/" in docker and "!data/juris/model/" in docker
    git = _lines(REPO / ".gitignore")
    assert f"!/lit-backend/{CARD.as_posix()}" in git and f"!/lit-backend/{ARTIFACT.as_posix()}" not in git


# --- fetching from the private dataset repo ----------------------------------------------------------------------------

@pytest.fixture()
def hub(tmp_path, monkeypatch):
    """A fake Hub: hf_hub_download copies a prepared file; settings point at a repo; MODEL_PATH is a temp location with a card."""
    good = tmp_path / "remote" / "juris.joblib"
    good.parent.mkdir()
    good.write_bytes(b"pretend this is a model")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model_card.json").write_text(json.dumps({"artifact_sha256": hashlib.sha256(good.read_bytes()).hexdigest()}))
    monkeypatch.setattr(juris, "MODEL_PATH", model_dir / "juris.joblib")
    monkeypatch.setattr(juris, "get_settings", lambda: SimpleNamespace(
        JURIS_MODEL_PATH="", PRECEDENT_ARTIFACT_REPO="owner/repo", JURIS_ARTIFACT_SUBDIR="juris/v2", JURIS_ARTIFACT_REVISION="main",
        HF_DATASET_TOKEN="", HUGGINGFACE_API_KEY="k"))
    calls = []

    def fake_download(repo_id, repo_type, filename, revision, token, local_dir):
        calls.append((repo_id, repo_type, filename, revision))
        dest = Path(local_dir) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(good.read_bytes())
        return str(dest)

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_download)
    return SimpleNamespace(good=good, model_dir=model_dir, calls=calls)


def test_a_missing_artifact_is_fetched_and_installed_when_its_hash_matches(hub):
    juris._ensure_artifact()
    assert juris.MODEL_PATH.read_bytes() == hub.good.read_bytes()
    assert hub.calls == [("owner/repo", "dataset", "juris/v2/juris.joblib", "main")]


def test_a_download_with_the_wrong_hash_is_refused(hub):
    (hub.model_dir / "model_card.json").write_text(json.dumps({"artifact_sha256": "0" * 64}))
    juris._ensure_artifact()
    assert not juris.MODEL_PATH.exists()


def test_no_card_hash_means_no_download(hub):
    (hub.model_dir / "model_card.json").write_text("{}")
    juris._ensure_artifact()
    assert not juris.MODEL_PATH.exists() and hub.calls == []


def test_an_existing_artifact_is_never_replaced_or_refetched(hub):
    juris.MODEL_PATH.write_bytes(b"local")
    juris._ensure_artifact()
    assert juris.MODEL_PATH.read_bytes() == b"local" and hub.calls == []
