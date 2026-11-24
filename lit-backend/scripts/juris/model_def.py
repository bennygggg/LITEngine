"""The Juris model definition (shared by training, evaluation and export)."""

from typing import Optional

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from services.juris_features import SIDES, SectionMultiHot, log1p_col

TOKEN_PATTERN = r"(?u)\b[a-zA-Z][a-zA-Z]+\b"
# Input columns by POSITION, so serving can pass a plain numpy object array (no pandas in the serving image).
TEXT, SIDE, NWORDS = 0, 1, 2   # column order of the model input: [text, side, n_words]


def make_juris(C: float = 4.0, max_features: int = 150_000, min_df: int = 5, use_sections: bool = True,
               use_text: bool = True, use_side: bool = True, class_weight: Optional[str] = "balanced",
               stop_words: Optional[list] = None) -> Pipeline:
    """TF-IDF (word 1-2grams) + appellant side + cited sections + length -> logistic regression.

    Linear on purpose: every coefficient is a word, phrase or input a reader can inspect, which is what the card shows."""
    parts = []
    if use_text:
        parts.append(("tfidf", TfidfVectorizer(
            ngram_range=(1, 2), min_df=min_df, max_df=0.6, max_features=max_features, sublinear_tf=True, strip_accents="unicode",
            token_pattern=TOKEN_PATTERN, dtype=np.float32, stop_words=stop_words), TEXT))
    if use_side:
        parts.append(("side", OneHotEncoder(categories=[SIDES], handle_unknown="ignore", sparse_output=True), [SIDE]))
    if use_sections:
        parts.append(("sections", SectionMultiHot(), TEXT))
    parts.append(("length", Pipeline([("log", FunctionTransformer(log1p_col, feature_names_out="one-to-one")), ("scale", StandardScaler(with_mean=False))]), [NWORDS]))
    pre = ColumnTransformer(parts, sparse_threshold=1.0)
    clf = LogisticRegression(C=C, solver="liblinear", class_weight=class_weight, max_iter=2000, random_state=42)
    return Pipeline([("preprocess", pre), ("clf", clf)])


def make_lgbm(stop_words: Optional[list] = None, n_estimators: int = 500, learning_rate: float = 0.05, num_leaves: int = 63) -> Pipeline:
    """Non-linear challenger: gradient boosting over sparse unigram TF-IDF + the same structured inputs."""
    import lightgbm as lgb
    pre = ColumnTransformer([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 1), min_df=10, max_df=0.6, max_features=20_000, sublinear_tf=True, strip_accents="unicode",
                                  token_pattern=TOKEN_PATTERN, dtype=np.float32, stop_words=stop_words), TEXT),
        ("side", OneHotEncoder(categories=[SIDES], handle_unknown="ignore", sparse_output=True), [SIDE]),
        ("sections", SectionMultiHot(), TEXT),
        ("length", Pipeline([("log", FunctionTransformer(log1p_col, feature_names_out="one-to-one"))]), [NWORDS]),
    ], sparse_threshold=1.0)
    clf = lgb.LGBMClassifier(n_estimators=n_estimators, learning_rate=learning_rate, num_leaves=num_leaves, subsample=0.8, subsample_freq=1,
                             colsample_bytree=0.5, min_child_samples=30, reg_lambda=1.0, n_jobs=6, random_state=42, verbose=-1)
    return Pipeline([("preprocess", pre), ("clf", clf)])
