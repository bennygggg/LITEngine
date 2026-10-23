"""
Precedent library artifact: vectors.npy + meta.jsonl + manifest.json (built by scripts/build_precedent_artifacts.py).

The vectors are byte-identical to the legacy JSON index, so the outcome model's `precedent_alignment` input keeps
the distribution it was trained on. Loading verifies the per-file sha256 from the manifest.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)

APP_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE_DIR = APP_ROOT / "data" / "precedent_artifacts"


@dataclass
class PrecedentArtifact:
    vectors: np.ndarray
    metadata: List[Dict[str, Any]]
    manifest: Dict[str, Any]
    path: Path

    @property
    def version(self) -> str:
        return str(self.manifest.get("artifact_version", "unknown"))

    @property
    def counts(self) -> Dict[str, int]:
        return dict(self.manifest.get("counts", {}))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_artifact(directory: Path) -> PrecedentArtifact:
    """Load and verify an artifact directory. Raises ValueError on any integrity problem."""
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"no manifest.json in {directory}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, info in manifest.get("files", {}).items():
        file_path = directory / name
        if not file_path.exists():
            raise ValueError(f"artifact file missing: {name}")
        if _sha256(file_path) != info["sha256"]:
            raise ValueError(f"artifact file failed its hash check: {name}")
    vectors = np.load(directory / "vectors.npy")
    metadata = [json.loads(line) for line in (directory / "meta.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if len(vectors) != len(metadata):
        raise ValueError(f"vector/metadata count mismatch: {len(vectors)} vs {len(metadata)}")
    return PrecedentArtifact(vectors=vectors, metadata=metadata, manifest=manifest, path=directory)


def _download(repo: str, revision: str, subdir: str, token: Optional[str]) -> Optional[Path]:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:  # pragma: no cover — huggingface_hub ships with sentence-transformers
        logger.warning("huggingface_hub is not installed; cannot fetch the precedent artifact")
        return None
    try:
        root = snapshot_download(
            repo_id=repo, repo_type="dataset", revision=revision, token=token or None,
            allow_patterns=[f"{subdir}/*"], local_dir=str(DEFAULT_CACHE_DIR / "_download"),
        )
    except Exception as exc:  # noqa: BLE001 — a missing/forbidden repo must not stop the app from starting
        logger.warning(f"Could not fetch precedent artifact {repo}@{revision}: {type(exc).__name__}")
        return None
    return Path(root) / subdir


def resolve_artifact() -> Optional[PrecedentArtifact]:
    """Find, verify and load the configured artifact; None means 'use the fixture index'."""
    settings = get_settings()
    candidates: List[Path] = []
    if settings.PRECEDENT_ARTIFACT_DIR:
        candidates.append(Path(settings.PRECEDENT_ARTIFACT_DIR).expanduser())
    elif settings.PRECEDENT_ARTIFACT_REPO:
        token = settings.HF_DATASET_TOKEN or settings.HUGGINGFACE_API_KEY
        fetched = _download(settings.PRECEDENT_ARTIFACT_REPO, settings.PRECEDENT_ARTIFACT_REVISION,
                            settings.PRECEDENT_ARTIFACT_SUBDIR, token)
        if fetched:
            candidates.append(fetched)
    for directory in candidates:
        try:
            artifact = load_artifact(directory)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Precedent artifact at {directory} is unusable: {exc}")
            continue
        logger.info(f"Loaded precedent artifact {artifact.version}: {artifact.counts}")
        return artifact
    return None
