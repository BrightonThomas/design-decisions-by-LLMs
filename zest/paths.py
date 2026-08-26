"""Shared filesystem layout for the TerminalBench trajectory pipeline.

All data lands under the repository's data/ directory by default; override with the
ZEST_DATA_DIR environment variable.
"""

import os
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("ZEST_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))

RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
CURATED_DIR = DATA_DIR / "curated"

RAW_TBENCH20 = RAW_DIR / "tbench2.0"
RAW_TBENCH21 = RAW_DIR / "tbench2.1"

CURATED_TBENCH20 = CURATED_DIR / "terminal_bench_2_0" / "trajectories.jsonl"
CURATED_TBENCH21 = CURATED_DIR / "terminal_bench_2_1" / "trajectories.jsonl"
CURATED_TERMINAL_BENCH = {
    "tbench": CURATED_TBENCH20,
    "tbench21": CURATED_TBENCH21,
}


def ensure_dirs() -> None:
    for d in (NORMALIZED_DIR, RAW_TBENCH20, RAW_TBENCH21):
        d.mkdir(parents=True, exist_ok=True)


def replace_with_retry(tmp: Path, dest: Path, retries: int = 5, base_delay: float = 0.05) -> None:
    """`tmp.replace(dest)` with retries on PermissionError. Windows can
    transiently deny a rename if antivirus/search-indexer/cloud-sync briefly
    has `dest` open for scanning; a short backoff almost always clears it.
    Re-raises if every attempt still fails."""
    for attempt in range(retries):
        try:
            tmp.replace(dest)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
