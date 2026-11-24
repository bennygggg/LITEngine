"""
Proper-noun stop list. People's names (surnames especially) and place names are identity proxies: a model that scores
"kaur" or "bhopal" as evidence for or against an appeal is learning who and where, not what happened. This builds a list of
tokens that are (almost) always capitalised mid-sentence - label-free, so it can be learned on the whole corpus - and the
vectoriser drops them. Structural legal words (Court, State, Section, Act ...) are kept.

    .venv-juris/bin/python -m scripts.juris.names --sample 20000
"""

import argparse
import json
import re
import sys
from typing import Dict, Iterable, List

import pandas as pd

from scripts.juris import paths
from scripts.juris.corpus import load_corpus

NAMES_PATH = paths.DATA / "names.json"
_TOKEN = re.compile(r"[A-Za-z]{3,}")

KEEP = frozenset("""court courts state states section sections act acts code high judge judges magistrate sessions appellant appellants accused
respondent respondents prosecution complainant learned trial additional district india indian penal criminal procedure evidence supreme constitution
article police station special public prosecutor counsel advocate government central union investigation bureau narcotic drugs psychotropic
substances negotiable instruments arms protection children sexual offences scheduled castes tribes atrocities prevention excise customs
cheque bank hospital doctor medical forensic laboratory report exhibit witness witnesses pw dw ipc bns crpc cr pc ndps pocso nia cbi fir
hindu muslim christian sikh""".split())


def proper_noun_tokens(texts: Iterable[str], min_count: int = 8, ratio: float = 0.85) -> List[str]:
    cap: Dict[str, int] = {}
    tot: Dict[str, int] = {}
    for text in texts:
        for m in _TOKEN.finditer(text):
            tok = m.group(0)
            if tok.isupper():                      # headings and acronyms say nothing about proper nouns
                continue
            i = m.start() - 1
            while i >= 0 and text[i] in " \t\"'(":
                i -= 1
            if i < 0 or text[i] in ".?!:;\n":      # sentence start: capitalisation is uninformative
                continue
            low = tok.lower()
            tot[low] = tot.get(low, 0) + 1
            if tok[0].isupper():
                cap[low] = cap.get(low, 0) + 1
    names = [t for t, n in tot.items() if n >= min_count and cap.get(t, 0) / n >= ratio and t not in KEEP]
    return sorted(set(names) | {"name"})           # "[NAME]" is the masking placeholder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20000)
    ap.add_argument("--min-count", type=int, default=8)
    ap.add_argument("--ratio", type=float, default=0.85)
    args = ap.parse_args()
    D = load_corpus(columns=["t0"])
    if len(D) > args.sample:
        D = D.sample(args.sample, random_state=1)
    names = proper_noun_tokens(D["t0"], args.min_count, args.ratio)
    NAMES_PATH.write_text(json.dumps(names))
    print(f"{len(names)} proper-noun tokens from {len(D)} documents; sample: {names[::max(1, len(names)//40)][:40]}")


def load_names() -> List[str]:
    return json.loads(NAMES_PATH.read_text()) if NAMES_PATH.exists() else []


if __name__ == "__main__":
    sys.exit(main())
