"""Training-side alias: the tier definitions live in services/juris_text.py so serving uses the identical code."""

from services.juris_text import (  # noqa: F401
    CUE_RE, MIN_HEAD_CHARS, MIN_HEAD_FRAC, T1_WINDOW, T2_CAP, VERDICT_RE, leak_hits, tier1, tier2,
)
