"""Evaluation metrics with uncertainty: point estimates, bootstrap CIs, paired tests, calibration."""

from typing import Callable, Dict, List, Tuple

import numpy as np
from scipy import stats
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss, f1_score, log_loss, roc_auc_score


def ece(y: np.ndarray, p: np.ndarray, bins: int = 15) -> float:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(total)


def metrics(y: np.ndarray, p: np.ndarray, thr: float = 0.5) -> Dict[str, float]:
    pred = (p >= thr).astype(int)
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "n": int(len(y)), "acc": float(accuracy_score(y, pred)), "bal_acc": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro")), "f1_succeeds": float(f1_score(y, pred, pos_label=1)),
        "f1_dismissed": float(f1_score(y, pred, pos_label=0)),
        "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        "brier": float(brier_score_loss(y, pc)), "logloss": float(log_loss(y, pc)), "ece": ece(y, pc),
    }


_FN: Dict[str, Callable] = {
    "acc": lambda y, p: accuracy_score(y, p >= 0.5), "auc": lambda y, p: roc_auc_score(y, p),
    "macro_f1": lambda y, p: f1_score(y, (p >= 0.5).astype(int), average="macro"),
    "bal_acc": lambda y, p: balanced_accuracy_score(y, (p >= 0.5).astype(int)),
}


def bootstrap_ci(y: np.ndarray, p: np.ndarray, names: List[str] = ("acc", "macro_f1", "auc", "bal_acc"), n: int = 1000,
                 seed: int = 13, clusters: np.ndarray = None) -> Dict[str, Tuple[float, float]]:
    """Percentile 95% CI. With `clusters` the resampling unit is the cluster (e.g. near-duplicate group), not the case."""
    rng = np.random.default_rng(seed)
    N = len(y)
    if clusters is None:
        draws = [rng.integers(0, N, N) for _ in range(n)]
    else:
        uniq, inv = np.unique(clusters, return_inverse=True)
        members = [np.where(inv == k)[0] for k in range(len(uniq))]
        draws = []
        for _ in range(n):
            pick = rng.integers(0, len(uniq), len(uniq))
            draws.append(np.concatenate([members[k] for k in pick]))
    out = {}
    for name in names:
        vals = []
        for d in draws:
            if name == "auc" and len(np.unique(y[d])) < 2:
                continue
            vals.append(_FN[name](y[d], p[d]))
        out[name] = (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))
    return out


def paired_bootstrap(y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray, metric: str = "acc", n: int = 1000, seed: int = 17) -> Dict[str, float]:
    """metric(A) - metric(B) on identical resamples."""
    rng = np.random.default_rng(seed)
    N = len(y)
    diffs = []
    for _ in range(n):
        d = rng.integers(0, N, N)
        if metric == "auc" and len(np.unique(y[d])) < 2:
            continue
        diffs.append(_FN[metric](y[d], p_a[d]) - _FN[metric](y[d], p_b[d]))
    diffs = np.array(diffs)
    return {"diff": float(_FN[metric](y, p_a) - _FN[metric](y, p_b)), "lo": float(np.percentile(diffs, 2.5)), "hi": float(np.percentile(diffs, 97.5))}


def mcnemar(y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray) -> Dict[str, float]:
    """Exact McNemar test on the discordant pairs (A right & B wrong vs the reverse)."""
    ca, cb = ((p_a >= 0.5).astype(int) == y), ((p_b >= 0.5).astype(int) == y)
    b, c = int((ca & ~cb).sum()), int((~ca & cb).sum())
    pval = float(stats.binomtest(b, b + c, 0.5).pvalue) if (b + c) > 0 else 1.0
    return {"a_right_b_wrong": b, "a_wrong_b_right": c, "p_value": pval}


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> List[Dict[str, float]]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        rows.append({"lo": float(edges[b]), "hi": float(edges[b + 1]), "n": int(m.sum()),
                     "mean_pred": float(p[m].mean()) if m.any() else float("nan"), "frac_pos": float(y[m].mean()) if m.any() else float("nan")})
    return rows
