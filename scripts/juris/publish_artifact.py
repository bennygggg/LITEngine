"""
Publish or fetch the Juris artifact through the private HF dataset repo (the Space rejects binary files in git).

    .venv-juris/bin/python -m scripts.juris.publish_artifact publish    # upload juris.joblib to <repo>/juris/v1/ (checks the sha256 against the card)
    .venv-juris/bin/python -m scripts.juris.publish_artifact fetch      # fresh clone: download it and verify it against the committed card

The repo defaults to the one the Space already reads (PRECEDENT_ARTIFACT_REPO / docs/RUNBOOK.md).
"""

import argparse
import hashlib
import json
import shutil
import sys

from scripts.juris import paths

DEFAULT_REPO = "thebenmerlin/lit-precedent-index"
SUBDIR = "juris/v1"


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["publish", "fetch"])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    args = ap.parse_args()
    from huggingface_hub import HfApi, hf_hub_download

    card = json.loads((paths.MODEL_DIR / "model_card.json").read_text())
    artifact = paths.MODEL_DIR / "juris.joblib"
    if args.action == "publish":
        if sha256(artifact) != card["artifact_sha256"]:
            sys.exit("juris.joblib does not match the sha256 in model_card.json: re-run export_artifact first")
        info = HfApi().upload_file(path_or_fileobj=str(artifact), path_in_repo=f"{SUBDIR}/juris.joblib", repo_id=args.repo, repo_type="dataset",
                                   commit_message=f"Juris {card['version']} ({card['artifact_sha256'][:8]})")
        print(f"published {card['version']} to {args.repo}/{SUBDIR}/juris.joblib: {info}")
    else:
        got = hf_hub_download(args.repo, f"{SUBDIR}/juris.joblib", repo_type="dataset", local_dir=str(paths.MODEL_DIR / "_download"))
        from pathlib import Path
        if sha256(Path(got)) != card["artifact_sha256"]:
            sys.exit("the downloaded artifact does not match the sha256 in model_card.json; not installing it")
        shutil.copyfile(got, artifact)
        print(f"fetched and verified {card['version']}")


if __name__ == "__main__":
    sys.exit(main())
