"""Filesystem layout for the Juris pipeline. Everything under data/juris/ except model/ is gitignored."""

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
DATA = BACKEND / "data" / "juris"
INDEX_DIR = DATA / "index"            # candidate cases from S3 metadata (no text)
PARTS_DIR = INDEX_DIR / "parts"       # one small filtered parquet per (year, court, bench) partition
TEXT_DIR = DATA / "text"              # extracted judgment text shards (zstd parquet); PDFs are deleted after extraction
REPORT_DIR = DATA / "reports"
PAPER_DIR = REPORT_DIR / "paper"
MODEL_DIR = DATA / "model"            # the only tracked subdirectory: juris.joblib + model_card.json
LOCAL_HC_METADATA = BACKEND / "data" / "bulk_corpus" / "hc_metadata"   # cache from earlier sessions (optional)

HC_BUCKET = "indian-high-court-judgments"
SC_BUCKET = "indian-supreme-court-judgments"
REGION = "ap-south-1"

CANDIDATES = INDEX_DIR / "hc_criminal_appeals.parquet"


def ensure_dirs() -> None:
    for d in (PARTS_DIR, TEXT_DIR, REPORT_DIR, PAPER_DIR, MODEL_DIR):
        d.mkdir(parents=True, exist_ok=True)
