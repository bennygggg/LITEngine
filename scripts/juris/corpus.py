"""Corpus access: load the built corpus (parts + keep list) with only the columns a step needs."""

from typing import List, Optional

import pandas as pd

from scripts.juris import paths

CORPUS_DIR = paths.DATA / "corpus"
KEEP = CORPUS_DIR / "keep.parquet"


def load_corpus(columns: Optional[List[str]] = None, kept_only: bool = True) -> pd.DataFrame:
    parts = sorted(CORPUS_DIR.glob("part-*.parquet"))
    cols = None if columns is None else sorted(set(columns) | {"cnr"})
    df = pd.concat([pd.read_parquet(f, columns=cols) for f in parts], ignore_index=True)
    if kept_only and KEEP.exists():
        keep = pd.read_parquet(KEEP)
        df = df[df["cnr"].isin(keep.loc[keep["keep"], "cnr"])]
    return df.reset_index(drop=True)
