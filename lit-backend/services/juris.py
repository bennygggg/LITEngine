"""
Juris — serves the project's trained appeal-outcome model (juris.joblib) for the live outcome estimate.

Juris reads the PRE-REASONING part of a case text (facts, trial-court findings, grounds and submissions: the same cut,
`services.juris_text.tier2`, that its training data went through) plus who is appealing. It does not read the appellate
court's reasoning, and it does not infer the appellant: `appellant_type` is a direct user input.

The artifact is a `CalibratedJuris` (TF-IDF + appellant side + cited sections + length -> logistic regression, then Platt
scaling). It is loaded once at import; if loading or validation fails for any reason, `is_juris_loaded()` is False and
`predict_juris()` returns a clearly marked stub instead of raising, so callers fall back to the heuristic and the endpoint
never errors.
"""

import hashlib
import json
import math
import shutil
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from config import get_settings
from models.schemas import JurisContribution, JurisResult, ScoreComponent, SimulationResult, StructuredCaseProfile
from services.juris_features import SIDES, CalibratedJuris
from services.juris_text import tier2
from services.simulator import PROB_MAX, PROB_MIN
from utils.logger import get_logger

logger = get_logger(__name__)

# The model is fitted on a DataFrame (training) and called with a plain array (serving, no pandas); columns are positional, so the
# feature-name notice is noise.
warnings.filterwarnings("ignore", message="X does not have valid feature names")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "juris" / "model" / "juris.joblib"
MODEL_PATH = Path(get_settings().JURIS_MODEL_PATH).expanduser() if get_settings().JURIS_MODEL_PATH else DEFAULT_MODEL_PATH

APPELLANT_TYPE_CATEGORIES = list(SIDES)
EXPECTED_CLASSES = ["dismissed", "succeeds"]
ARTIFACT_SCHEMA = "juris-text-v1"
TOP_PHRASES = 8            # individual phrases listed in the contributions; the rest are summed into one "other wording" row
TOP_N_EXPLANATION = 3
LONG_DOC_WORDS = 400       # documents this long are judgments (cut at 60 %); shorter ones are filings (cut only at a cue or verdict)
MIN_WORDS = 40             # below this the text says too little for a text model to mean anything

APPELLANT_DISPLAY = {
    "accused_appeal": "Appeal type: accused's own appeal",
    "state_appeal": "Appeal type: State/complainant appeal",
    "unclear": "Appeal type: not specified",
}


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

_model: Optional[CalibratedJuris] = None
_load_error: Optional[str] = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _expected_sha() -> Optional[str]:
    """The artifact hash pinned by the model card that is committed next to it (text, so git accepts it)."""
    try:
        return json.loads((MODEL_PATH.parent / "model_card.json").read_text(encoding="utf-8")).get("artifact_sha256")
    except Exception:  # noqa: BLE001
        return None


def _ensure_artifact() -> None:
    """If the artifact is not on disk, fetch it from the private HF dataset repo and install it only if its sha256 matches the card.

    Binary files cannot live in the Space's git repo, so the Space downloads Juris at start, the way it downloads the precedent library.
    Any failure leaves the file absent, and the app then runs on the heuristic (never crashes)."""
    settings = get_settings()
    if MODEL_PATH.exists() or settings.JURIS_MODEL_PATH or not settings.PRECEDENT_ARTIFACT_REPO:
        return
    expected = _expected_sha()
    if not expected:
        logger.warning("Juris artifact is absent and the model card pins no sha256; refusing to download an unverified model")
        return
    try:
        from huggingface_hub import hf_hub_download
        downloaded = Path(hf_hub_download(
            repo_id=settings.PRECEDENT_ARTIFACT_REPO, repo_type="dataset", filename=f"{settings.JURIS_ARTIFACT_SUBDIR}/juris.joblib",
            revision=settings.JURIS_ARTIFACT_REVISION, token=(settings.HF_DATASET_TOKEN or settings.HUGGINGFACE_API_KEY) or None,
            local_dir=str(MODEL_PATH.parent / "_download"),
        ))
    except Exception as exc:  # noqa: BLE001 - a missing or forbidden repo must not stop the app from starting
        logger.warning(f"Could not fetch the Juris artifact: {type(exc).__name__}")
        return
    if _sha256(downloaded) != expected:
        logger.error("The downloaded Juris artifact does not match the sha256 in the model card; not installing it")
        return
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(downloaded, MODEL_PATH)
    logger.info("Fetched and verified the Juris artifact from the private dataset repo")


def _validate(model: Any) -> None:
    if not isinstance(model, CalibratedJuris):
        raise ValueError(f"artifact is a {type(model).__name__}, not a CalibratedJuris")
    meta = getattr(model, "meta", None) or {}
    if meta.get("schema") != ARTIFACT_SCHEMA:
        raise ValueError(f"artifact schema {meta.get('schema')!r} != {ARTIFACT_SCHEMA!r}")
    _validate_one(model)
    for side, sub in (getattr(model, "side_models", None) or {}).items():
        if side not in APPELLANT_TYPE_CATEGORIES:
            raise ValueError(f"side model for unknown appeal side {side!r}")
        if not isinstance(sub, CalibratedJuris):
            raise ValueError(f"side model {side!r} is not a CalibratedJuris")
        _validate_one(sub)


def _validate_one(model: CalibratedJuris) -> None:
    if list(model.classes_) != EXPECTED_CLASSES:
        raise ValueError(f"unexpected classes_ {list(model.classes_)}")
    clf = model.pipeline.named_steps["clf"]
    n = len(model.feature_kinds_)
    if clf.coef_.shape[-1] != n or len(model.feature_means_) != n or len(model.feature_labels_) != n:
        raise ValueError("feature manifest does not match the classifier's coefficient vector")
    if list(clf.classes_) != [0, 1]:
        raise ValueError(f"unexpected inner classes_ {list(clf.classes_)}")


def _load_model() -> None:
    global _model, _load_error
    try:
        import joblib
    except ImportError as exc:
        _load_error = f"joblib not installed: {exc}"
        logger.warning(f"Juris unavailable — {_load_error}. Falling back to heuristic only.")
        return
    if not MODEL_PATH.exists():
        _load_error = f"model file not found at {MODEL_PATH}"
        logger.warning(f"Juris unavailable — {_load_error}. Falling back to heuristic only.")
        return
    try:
        model = joblib.load(MODEL_PATH)
        _validate(model)
    except Exception as exc:  # noqa: BLE001 - any failure must degrade to the heuristic, never crash the app
        _load_error = f"failed to load/validate {MODEL_PATH}: {exc}"
        logger.warning(f"Juris unavailable — {_load_error}. Falling back to heuristic only.")
        return
    _model = model
    logger.info(f"Loaded Juris {model.meta.get('version')} from {MODEL_PATH}")


_ensure_artifact()
_load_model()


def is_juris_loaded() -> bool:
    return _model is not None


def juris_meta() -> Dict[str, Any]:
    return dict(_model.meta) if _model is not None else {}


def _pick(appellant_type: str) -> CalibratedJuris:
    """The model that scores this appeal side: a side-specific model if the artifact carries one (State appeals), else the joint model."""
    assert _model is not None
    return (getattr(_model, "side_models", None) or {}).get(appellant_type, _model)


def baseline_logit(appellant_type: str) -> Optional[float]:
    """Where 'a typical training case' sits for the model that scores this side (the contributions add up to logit - this)."""
    return _pick(appellant_type).baseline_logit if _model is not None else None


def baseline_p(appellant_type: str) -> Optional[float]:
    return getattr(_pick(appellant_type), "baseline_p_", None) if _model is not None else None


# ---------------------------------------------------------------------------
# Input preparation
# ---------------------------------------------------------------------------

def profile_to_text(profile: StructuredCaseProfile) -> str:
    """Fallback text when only a structured profile exists (legacy endpoints). Much thinner than a real case text."""
    parts: List[str] = []
    if profile.parties.petitioner or profile.parties.respondent:
        parts.append(f"{profile.parties.petitioner or 'The appellant'} versus {profile.parties.respondent or 'the respondent'}.")
    if profile.ipc_sections:
        parts.append("Charged under " + ", ".join(profile.ipc_sections) + ".")
    parts.extend(profile.key_facts)
    parts.extend(profile.legal_issues)
    if profile.relief_sought:
        parts.append(f"The appeal seeks {profile.relief_sought}.")
    return "\n".join(parts)


def prepare_text(text: str) -> Tuple[str, int]:
    """Apply the training-time pre-reasoning cut to a user's document. Returns (text read by Juris, words)."""
    cut, _ = tier2(text, apply_cap=len(text.split()) >= LONG_DOC_WORDS)
    return cut, len(cut.split())


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------

def _direction(contribution: float) -> str:
    return "succeeds" if contribution >= 0 else "dismissed"


def _sentence(kind: str, label: str, contribution: float) -> str:
    d = _direction(contribution)
    if kind == "side":
        phrasing = {
            "accused_appeal": "This is the accused's own appeal against conviction",
            "state_appeal": "This is a State/complainant appeal against acquittal",
            "unclear": "Appeal type wasn't specified",
        }[label]
        return f"{phrasing}, which pushed toward '{d}'."
    if kind == "section":
        return f"Section {label} is cited in the case text, which pushed toward '{d}'."
    if kind == "length":
        return f"The length of the text read pushed slightly toward '{d}'."
    return f"The wording “{label}” appears in the case text and pushed toward '{d}'."


def _contributions(model: CalibratedJuris, X) -> Tuple[float, List[JurisContribution]]:
    """Signed log-odds contributions relative to a typical training case: a * coef_j * (x_j - mean_j), plus a summed remainder."""
    pre = model.pipeline.named_steps["preprocess"]
    clf = model.pipeline.named_steps["clf"]
    row = pre.transform(X).tocsr()
    coef = clf.coef_[0]
    means = model.feature_means_
    kinds, labels = model.feature_kinds_, model.feature_labels_
    active = dict(zip(row.indices.tolist(), row.data.tolist()))
    contributions: Dict[int, Tuple[float, float]] = {}
    for j, x in active.items():
        contributions[j] = (x, model.a * coef[j] * (x - means[j]))
    for j in model.structured_idx_:           # the inactive appellant categories and absent sections still move the baseline
        if j not in contributions:
            contributions[j] = (0.0, model.a * coef[j] * (0.0 - means[j]))
    out: List[JurisContribution] = []
    phrases: List[Tuple[int, float, float]] = []
    other_n = 0
    absent_sections = 0.0
    for j, (x, c) in contributions.items():
        kind = kinds[j]
        if kind == "phrase":
            phrases.append((j, x, c))
            continue
        if kind == "section" and x == 0.0:
            absent_sections += c                    # sections not cited here: folded into "other wording" so the bars still add up
            continue
        label = labels[j]
        feature = f"appellant_type={label}" if kind == "side" else f"section_{label}" if kind == "section" else "length"
        display = APPELLANT_DISPLAY.get(label, label) if kind == "side" else f"Section {label} cited" if kind == "section" else "Length of text read"
        out.append(JurisContribution(feature=feature, display_name=display, value=float(x), contribution=float(c), explanation=_sentence(kind, label, c)))
    phrases.sort(key=lambda t: -abs(t[2]))
    # Phrases absent from this text still sit below/above the training mean; folding them into "other wording" makes the bars
    # add up exactly: baseline_logit + sum(contributions) == the model's logit.
    active_text_mean_term = sum(float(coef[j]) * float(means[j]) for j, _, _ in phrases)
    other_sum = -model.a * (model.text_mean_term_ - active_text_mean_term) + absent_sections
    for j, x, c in phrases[:TOP_PHRASES]:
        label = labels[j]
        out.append(JurisContribution(feature=f"phrase:{label}", display_name=f"“{label}”", value=float(x), contribution=float(c),
                                     explanation=_sentence("phrase", label, c)))
    for _, _, c in phrases[TOP_PHRASES:]:
        other_sum += c
        other_n += 1
    if abs(other_sum) > 1e-9:
        out.append(JurisContribution(feature="phrase:other", display_name="All other wording", value=float(other_n), contribution=float(other_sum),
                                     explanation=f"All the remaining wording together pushed toward '{_direction(other_sum)}'."))
    out.sort(key=lambda c: abs(c.contribution), reverse=True)
    z = float(model.decision_function(X)[0])
    return z, out


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

def _fallback_result(reason: Optional[str] = None) -> JurisResult:
    return JurisResult(
        predicted_class="unknown", probability=0.0, probabilities={"dismissed": 0.0, "succeeds": 0.0}, feature_contributions=[],
        explanation_sentences=[reason or "Juris is currently unavailable — showing the heuristic result only."],
        key_strengths=[], key_weaknesses=[], recommendation="Juris unavailable this session — see the heuristic result.",
        model_loaded=False, model_version=None,
    )


def predict_juris(text: str, appellant_type: str, input_basis: str = "case_text", pre_cut: bool = False) -> JurisResult:
    """
    Args:
        text: the case text (a full document is cut to its pre-reasoning part here) or a profile summary.
        pre_cut: the text is already the pre-reasoning part (scenario edits are applied after the cut), so do not cut again.
        appellant_type: "accused_appeal" | "state_appeal" | "unclear" — a direct user input, never inferred from the text.
    """
    if _model is None:
        return _fallback_result()
    if appellant_type not in APPELLANT_TYPE_CATEGORIES:
        appellant_type = "unclear"
    read_text, n_words = (text or "", len((text or "").split())) if pre_cut else prepare_text(text or "")
    if n_words < MIN_WORDS:
        logger.warning(f"predict_juris: only {n_words} words to read — not enough for a text model")
        return _fallback_result("There is too little text to estimate from — Juris needs the facts and grounds of the case.")
    X = np.array([[read_text, appellant_type, n_words]], dtype=object)   # column order: text, side, n_words
    active_model = _pick(appellant_type)
    try:
        proba = active_model.predict_proba(X)[0]
        _, contributions = _contributions(active_model, X)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"predict_juris: inference failed, falling back: {exc}")
        return _fallback_result()
    probabilities = {"dismissed": float(proba[0]), "succeeds": float(proba[1])}
    predicted = "succeeds" if proba[1] >= 0.5 else "dismissed"
    active = [c for c in contributions if abs(c.contribution) > 1e-9]
    p = probabilities["succeeds"]
    if p >= 0.7:
        base = "The case appears favorable — Juris estimates a good chance of success."
    elif p >= 0.5:
        base = "The outcome is uncertain per Juris — success depends on the weaker factors below."
    else:
        base = "Juris estimates significant headwinds for this appeal."
    weaknesses = [c.explanation for c in active if c.contribution < 0][:3]
    return JurisResult(
        predicted_class=predicted, probability=probabilities[predicted], probabilities=probabilities, feature_contributions=contributions,
        explanation_sentences=[c.explanation for c in active[:TOP_N_EXPLANATION]],
        key_strengths=[c.explanation for c in active if c.contribution > 0][:3], key_weaknesses=weaknesses,
        recommendation=base + (f" Consider addressing: {weaknesses[0].lower()}" if weaknesses else ""),
        model_loaded=True, model_version=str(_model.meta.get("version", MODEL_PATH.name)),
        words_read=n_words, input_basis=input_basis,
    )


# ---------------------------------------------------------------------------
# Reshape into the legacy SimulationResult shape (when Juris is "primary" it populates the top-level response.result)
# ---------------------------------------------------------------------------

def _risk_from_probability(p: float) -> Dict[str, str]:
    if p >= 0.7:
        return {"level": "Favorable", "color": "green"}
    if p >= 0.5:
        return {"level": "Uncertain", "color": "amber"}
    return {"level": "Unfavorable", "color": "red"}


def juris_to_simulation_result(juris: JurisResult) -> SimulationResult:
    """
    Projects Juris's output into the existing SimulationResult shape so it can populate the top-level (legacy) response
    field without a schema change. win_probability = P(succeeds): this case's own appeal, whoever filed it.

    score_breakdown does not map cleanly: ScoreComponent.weight is a fixed a-priori importance in [0, 1], while Juris's
    contributions are signed, case-specific log-odds terms. weight = weighted_score = |contribution| / sum(|contributions|)
    (this case's share of total influence, >= 0, sums to ~1); the direction is in the `explanation` text.
    """
    probability = juris.probabilities.get("succeeds", juris.probability)
    probability = max(PROB_MIN, min(PROB_MAX, probability))
    total_abs = sum(abs(c.contribution) for c in juris.feature_contributions) or 1.0
    breakdown = [
        ScoreComponent(
            component=c.display_name, weight=round(abs(c.contribution) / total_abs, 4), raw_score=round(max(0.0, min(1.0, c.value)), 4),
            weighted_score=round(abs(c.contribution) / total_abs, 4), explanation=c.explanation,
        )
        for c in juris.feature_contributions if abs(c.contribution) > 1e-9
    ]
    return SimulationResult(
        win_probability=round(probability, 4), risk_assessment=_risk_from_probability(probability), score_breakdown=breakdown,
        key_strengths=juris.key_strengths, key_weaknesses=juris.key_weaknesses, recommendation=juris.recommendation,
    )
