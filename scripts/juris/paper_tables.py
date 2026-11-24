"""
Turn the reports into tables for the paper and the black book: CSV (for plots) and LaTeX (for tables), plus a generated
`juris-metrics.generated.tex` that mirrors the macros in blackbook/config/juris-metrics.tex.

    .venv-juris/bin/python -m scripts.juris.paper_tables
"""

import json
import sys
from typing import Any, Dict, List

import pandas as pd

from scripts.juris import paths

OUT = paths.PAPER_DIR


def pct(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f}\\%"


def ci(ci_pair: Any, d: int = 1) -> str:
    return f"[{100 * ci_pair[0]:.{d}f}, {100 * ci_pair[1]:.{d}f}]" if ci_pair else ""


def write(name: str, df: pd.DataFrame, latex: bool = True, col_format: str = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"{name}.csv", index=False)
    if latex:
        (OUT / f"{name}.tex").write_text(df.to_latex(index=False, escape=False, column_format=col_format))


def main() -> None:
    final = json.loads((paths.REPORT_DIR / "final.json").read_text())
    dev = json.loads((paths.REPORT_DIR / "dev.json").read_text())
    funnel = json.loads((paths.REPORT_DIR / "corpus_funnel.json").read_text()) if (paths.REPORT_DIR / "corpus_funnel.json").exists() else {}
    idx = json.loads((paths.INDEX_DIR / "index_funnel.json").read_text()) if (paths.INDEX_DIR / "index_funnel.json").exists() else {}
    n = final["n"]

    # --- main results on the untouched test split
    rows: List[Dict[str, str]] = []

    def add(name: str, r: Dict[str, Any]) -> None:
        c = r.get("ci", {})
        rows.append({"Model": name, "Accuracy (95\\% CI)": f"{pct(r['acc'])} {ci(c.get('acc'))}", "Balanced acc.": pct(r["bal_acc"]), "Macro-F1": pct(r["macro_f1"]),
                     "AUC": f"{r['auc']:.3f}" if r["auc"] == r["auc"] else "--", "Brier": f"{r['brier']:.3f}", "ECE": f"{r['ece']:.3f}"})

    add("Majority outcome", final["baselines"]["majority"])
    add("Appellant side only", final["baselines"]["side_only"])
    add("Metadata only (court, year, case type, side)", final["baselines"]["meta_only(bench,year,ctype,side)"])
    add("Juris (T2: pre-reasoning text)", final["tiers"]["T2 pre-reasoning (ships)"])
    if "lightgbm (challenger)" in final["baselines"]:
        add("Gradient boosting challenger", final["baselines"]["lightgbm (challenger)"])
    write("tab_main", pd.DataFrame(rows), col_format="lrrrrrr")

    # --- leakage tiers
    tr = []
    for name, r in final["tiers"].items():
        if "capped" not in name and "ships" not in name:
            continue
        tr.append({"Input to the model": name, "Accuracy (95\\% CI)": f"{pct(r['acc'])} {ci(r['ci'].get('acc'))}", "Macro-F1": pct(r["macro_f1"]), "AUC": f"{r['auc']:.3f}"})
    write("tab_tiers", pd.DataFrame(tr), col_format="lrrr")

    # --- ablations and sanity checks
    ab = []
    for name in ("T2 + proper nouns kept (ablation)", "shuffled-label sanity (should be ~chance)"):
        if name in final["baselines"]:
            r = final["baselines"][name]
            ab.append({"Variant": name, "Accuracy": pct(r["acc"]), "AUC": f"{r['auc']:.3f}", "Macro-F1": pct(r["macro_f1"])})
    for k, v in final.get("paired_tests_vs_juris", {}).items():
        ab.append({"Variant": f"Juris vs {k}: paired accuracy gain", "Accuracy": f"{100 * v['delta_acc']['diff']:+.1f} pts [{100 * v['delta_acc']['lo']:+.1f}, {100 * v['delta_acc']['hi']:+.1f}]",
                   "AUC": f"{v['delta_auc']['diff']:+.3f}", "Macro-F1": f"McNemar p={v['mcnemar']['p_value']:.2g}"})
    write("tab_ablation", pd.DataFrame(ab), col_format="lrrr")

    # --- corpus funnel
    fr = [("Criminal-appeal cases indexed (2008 onward)", idx.get("unique_cases")),
          ("  of which labelled succeeds / dismissed by the court record", sum(idx.get("label_counts", {}).get(k, 0) for k in ("succeeds", "dismissed"))),
          ("  of which 'disposed of' (label taken from the order text)", idx.get("label_counts", {}).get("neutral")),
          ("Order texts retrieved and extracted", funnel.get("text_docs_seen")),
          ("After quality, procedural-ending and label cross-check gates", funnel.get("after_quality_and_label_filters")),
          ("After near-duplicate removal", funnel.get("final_cases")),
          ("Merits judgments used by Juris (>= 800 words, not interlocutory, T2 >= 100 words)", n["total"]),
          ("  training (decided up to 2021)", n["train"]), ("  validation (2022)", n["val"]), ("  test (2023 onward)", n["test"])]
    write("tab_funnel", pd.DataFrame(fr, columns=["Stage", "Cases"]), col_format="lr")

    # --- breakdowns and curves (CSV for plots; the black book prints the top rows)
    pd.DataFrame(final["by_bench"]).to_csv(OUT / "tab_by_court.csv", index=False)
    pd.DataFrame(final["by_year"]).to_csv(OUT / "tab_by_year.csv", index=False)
    pd.DataFrame(final["by_side"]).to_csv(OUT / "tab_by_side.csv", index=False)
    pd.DataFrame(final["reliability"]).to_csv(OUT / "fig_reliability.csv", index=False)
    pd.DataFrame(dev["learning_curve"]).to_csv(OUT / "fig_learning_curve.csv", index=False)

    # --- black-book macros (every number the book prints about Juris comes from here)
    t2 = final["tiers"]["T2 pre-reasoning (ships)"]
    t1 = final["tiers"]["T1 order-stripped (same capped training set)"]
    t0 = final["tiers"]["T0 full text (same capped training set)"]
    t2c = final["tiers"]["T2 pre-reasoning (same capped training set)"]
    b = final["baselines"]
    base, side, meta = b["majority"], b["side_only"], b["meta_only(bench,year,ctype,side)"]
    card = json.loads((paths.MODEL_DIR / "model_card.json").read_text())
    cfg = final["config"]
    macros = {
        "jurisIndexed": f"{idx.get('unique_cases', 0):,}", "jurisIndexedLabelled": f"{sum(idx.get('label_counts', {}).get(k, 0) for k in ('succeeds', 'dismissed')):,}",
        "jurisFetched": f"{funnel.get('text_docs_seen', 0):,}", "jurisAfterGates": f"{funnel.get('after_quality_and_label_filters', 0):,}",
        "jurisMerits": f"{n['total']:,}", "jurisTrainN": f"{n['train']:,}", "jurisValN": f"{n['val']:,}", "jurisTestN": f"{n['test']:,}",
        "jurisCases": f"{card['trained_on']['n']:,}", "jurisCourts": str(card["trained_on"]["courts"]), "jurisPeriod": card["trained_on"]["period"],
        "jurisSucceeds": f"{card['trained_on']['class_balance']['succeeds']:,}", "jurisDismissed": f"{card['trained_on']['class_balance']['dismissed']:,}",
        "jurisTrainShare": pct(n["train_succeeds_share"], 0), "jurisTestShare": pct(n["test_succeeds_share"], 0),
        "jurisAcc": pct(t2["acc"]), "jurisAccLo": pct(t2["ci"]["acc"][0]), "jurisAccHi": pct(t2["ci"]["acc"][1]), "jurisAUC": f"{t2['auc']:.3f}",
        "jurisMacroF": pct(t2["macro_f1"]), "jurisBalAcc": pct(t2["bal_acc"]), "jurisFSucc": pct(t2["f1_succeeds"]), "jurisFDism": pct(t2["f1_dismissed"]),
        "jurisBase": pct(base["acc"]), "jurisSideAcc": pct(side["acc"]), "jurisSideAUC": f"{side['auc']:.3f}", "jurisMetaAcc": pct(meta["acc"]), "jurisMetaAUC": f"{meta['auc']:.3f}",
        "jurisTcapAcc": pct(t2c["acc"]), "jurisTcapAUC": f"{t2c['auc']:.3f}", "jurisTcapN": f"{final['n']['tier_comparison_train_cap']:,}", "jurisTzeroAcc": pct(t0["acc"]), "jurisTzeroAUC": f"{t0['auc']:.3f}", "jurisToneAcc": pct(t1["acc"]), "jurisToneAUC": f"{t1['auc']:.3f}",
        "jurisBrier": f"{t2['brier']:.3f}", "jurisECE": f"{t2['ece']:.3f}", "jurisC": f"{cfg['C']:g}", "jurisFeatures": f"{card['trained_on'].get('features', '150{,}000')}",
        "jurisTestPeriod": card["evaluation"]["period"],
    }
    if "T2 + proper nouns kept (ablation)" in b:
        macros["jurisNamesAcc"] = pct(b["T2 + proper nouns kept (ablation)"]["acc"]); macros["jurisNamesAUC"] = f"{b['T2 + proper nouns kept (ablation)']['auc']:.3f}"
    if "shuffled-label sanity (should be ~chance)" in b:
        sh = b["shuffled-label sanity (should be ~chance)"]; macros["jurisShuffAcc"] = pct(sh["acc"]); macros["jurisShuffAUC"] = f"{sh['auc']:.3f}"
    (OUT / "juris-metrics.generated.tex").write_text("% Generated by scripts/juris/paper_tables.py - do not edit by hand.\n" +
                                                    "\n".join(f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in macros.items()) + "\n")
    # --- the bar chart of Chapter 6 (accuracy and AUC x 100 on the test cases)
    cats = [("Majority outcome", base), ("Appeal type only", side), ("Metadata, no text", meta), ("Juris (ships)", t2), ("Order removed (ILDC)", t1), ("Full text (upper bound)", t0)]   # tiers: same capped training set
    acc_c = "".join(f"({{{n}}},{100 * r['acc']:.1f})" for n, r in cats)
    auc_c = "".join(f"({{{n}}},{100 * (r['auc'] if r['auc'] == r['auc'] else 0.5):.1f})" for n, r in cats)
    syms = ",".join(f"{{{n}}}" for n, _ in cats)
    (OUT / "fig-models.tex").write_text(r"""\begin{tikzpicture}
\begin{axis}[
  width=12.5cm, height=5.3cm, ybar, bar width=11pt, ymin=40, ymax=100,
  symbolic x coords={""" + syms + r"""}, xtick=data,
  x tick label style={font=\figsmall, align=center, text width=1.9cm}, y tick label style={font=\figsmall},
  ylabel={Score on the test cases}, ylabel style={font=\figsmall}, enlarge x limits=0.1,
  legend style={font=\figsmall, at={(0.5,1.08)}, anchor=south, legend columns=2, draw=none},
  nodes near coords, every node near coord/.append style={font=\figsmall, /pgf/number format/.cd, fixed, precision=1},
  ymajorgrids, grid style={dotted, gray}]
\addplot[fill=g20, draw=black, line width=0.6pt] coordinates {""" + acc_c + r"""};
\addplot[fill=white, draw=black, line width=0.6pt, postaction={pattern=north east lines}] coordinates {""" + auc_c + r"""};
\legend{Accuracy (\%), AUC ($\times 100$)}
\end{axis}
\end{tikzpicture}
""")
    print(f"wrote tables to {OUT}")
    print(json.dumps(macros, indent=2))


if __name__ == "__main__":
    sys.exit(main())
