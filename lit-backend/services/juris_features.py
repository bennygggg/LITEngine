"""
Feature transformers for Juris. These live in `services/` (not `scripts/`) because the pickled pipeline references them by
module path: the serving image must be able to import every class the artifact contains.

The model reads three columns, by position (a numpy object array at serving; a DataFrame in training):
    text     the pre-reasoning case text (facts, trial-court findings, grounds)
    side     appellant type: accused_appeal | state_appeal | unclear (a user input at serving; never inferred from the text)
    n_words  length of `text` in words
"""

import re
from typing import Iterable, List

import numpy as np
import scipy.sparse as sp
from sklearn.base import BaseEstimator, TransformerMixin

SIDES = ["accused_appeal", "state_appeal", "unclear"]

_SECTION_GROUP = re.compile(
    r"\b(?:sections?|secs?\.?|u/s\.?|us)\s+((?:\d{1,3}[A-Z]?(?:\s*\([0-9a-z]{1,3}\))*(?:\s*(?:,|/|and|&|-|to|r/w|read\s+with)\s*)?){1,8})",
    re.IGNORECASE,
)
_SECTION_NUM = re.compile(r"\d{1,3}[A-Za-z]?")
_SUBCLAUSE = re.compile(r"\([0-9a-z]{1,3}\)", re.IGNORECASE)


def extract_sections(text: str) -> List[str]:
    """Section numbers cited in the text ('302', '34', '498A'). Act names are not resolved: numbers collide across Acts."""
    found = set()
    for m in _SECTION_GROUP.finditer(text or ""):
        group = _SUBCLAUSE.sub("", m.group(1))           # "304B(1)" is section 304B, not sections 304B and 1
        for num in _SECTION_NUM.findall(group):
            found.add(num.upper())
    return sorted(found)


class SectionMultiHot(BaseEstimator, TransformerMixin):
    """Binary indicators for the `top_k` most common cited sections (so scenarios can add or remove a section)."""

    def __init__(self, top_k: int = 120, min_df: int = 20):
        self.top_k = top_k
        self.min_df = min_df

    def fit(self, X: Iterable[str], y=None):
        df: dict = {}
        for text in X:
            for s in extract_sections(text):
                df[s] = df.get(s, 0) + 1
        ranked = sorted((s for s, c in df.items() if c >= self.min_df), key=lambda s: (-df[s], s))
        self.vocab_ = ranked[: self.top_k]
        self._index = {s: i for i, s in enumerate(self.vocab_)}
        return self

    def transform(self, X: Iterable[str]):
        rows, cols = [], []
        n = 0
        for i, text in enumerate(X):
            n = i + 1
            for s in extract_sections(text):
                j = self._index.get(s)
                if j is not None:
                    rows.append(i); cols.append(j)
        return sp.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(n, len(self.vocab_)))

    def get_feature_names_out(self, input_features=None):
        return np.array([f"section_{s}" for s in self.vocab_])


def log1p_col(x):
    return np.log1p(np.asarray(x, dtype=np.float64))


class CalibratedJuris:
    """A fitted pipeline plus a Platt scaler (a, b): p(succeeds) = sigmoid(a * z + b), z = the pipeline's decision value.

    classes_ keeps the serving contract: ["dismissed", "succeeds"]; predict_proba columns follow that order.
    `finalize()` records the feature manifest (kind, label, training mean per column) that explanations are built from."""

    classes_ = np.array(["dismissed", "succeeds"])

    def __init__(self, pipeline, a: float = 1.0, b: float = 0.0, meta=None):
        self.pipeline = pipeline
        self.a = float(a)
        self.b = float(b)
        self.meta = dict(meta or {})
        self.side_models = {}          # appeal side -> a CalibratedJuris trained only on that side (e.g. 'state_appeal')

    def finalize(self, X_fit) -> "CalibratedJuris":
        pre = self.pipeline.named_steps["preprocess"]
        M = pre.transform(X_fit)
        self.feature_means_ = np.asarray(M.mean(axis=0)).ravel().astype(np.float32)
        kinds, labels = [], []
        for name in pre.get_feature_names_out():
            prefix, _, rest = str(name).partition("__")
            if prefix == "tfidf":
                kinds.append("phrase"); labels.append(rest)
            elif prefix == "side":
                kinds.append("side"); labels.append(re.sub(r"^(?:side|x\d+)_", "", rest, count=1))
            elif prefix == "sections":
                kinds.append("section"); labels.append(rest.replace("section_", "", 1))
            else:
                kinds.append("length"); labels.append(rest)
        self.feature_kinds_, self.feature_labels_ = kinds, labels
        self.structured_idx_ = [j for j, k in enumerate(kinds) if k != "phrase"]
        coef = self.pipeline.named_steps["clf"].coef_[0]
        text_idx = np.array([j for j, k in enumerate(kinds) if k == "phrase"], dtype=int)
        self.text_mean_term_ = float(np.dot(coef[text_idx], self.feature_means_[text_idx])) if len(text_idx) else 0.0
        # mean decision value over the training cases; baseline_logit = a * z_mean + b is where "a typical case" sits
        self.z_mean_ = float(self.pipeline.named_steps["clf"].intercept_[0] + np.dot(coef, self.feature_means_))
        return self

    @property
    def baseline_logit(self) -> float:
        return self.a * self.z_mean_ + self.b

    def decision_function(self, X):
        if hasattr(self.pipeline, "decision_function"):
            return np.asarray(self.pipeline.decision_function(X), dtype=np.float64)
        p = np.clip(self.pipeline.predict_proba(X)[:, 1], 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    def predict_proba(self, X):
        z = self.a * self.decision_function(X) + self.b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        return np.column_stack([1.0 - p, p])

    def predict(self, X):
        return self.classes_[(self.predict_proba(X)[:, 1] >= 0.5).astype(int)]
