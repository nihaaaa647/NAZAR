"""
Phase 0 - data & feature foundation.

Walks every per-constituency works_with_images.csv produced by
mplads_india_downloader.py, merges them into one master table, and derives
the fields every later phase (rules, Isolation Forest, NLP, CV) depends on.

Safe to re-run at any point while the scrape is still in progress - it just
re-reads whatever CSVs exist under mplads_india/ and overwrites the output.

Usage:
    python -m pipeline.consolidate
"""

import glob
import re
from pathlib import Path

import pandas as pd

RAW_ROOT = Path("mplads_india")
OUT_DIR = RAW_ROOT / "_consolidated"
OUT_PATH = OUT_DIR / "master_works.parquet"

LETTER_NO_RE = re.compile(r"^LN/MP(\d+)/(\d{4})-(\d{4})/(\d+)$")


def load_raw_works(root: Path = RAW_ROOT) -> pd.DataFrame:
    """Concatenate every works_with_images.csv under root. Different files can
    have slightly different columns (e.g. ATTACH_ID is absent whenever no
    work in that constituency had any attachment at all) - concat with a
    column union rather than assuming a fixed schema."""
    files = glob.glob(str(root / "**" / "works_with_images.csv"), recursive=True)
    if not files:
        raise FileNotFoundError(f"no works_with_images.csv found under {root}/")

    frames = []
    for f in files:
        df = pd.read_csv(f)
        df["_source_csv"] = f
        frames.append(df)

    return pd.concat(frames, ignore_index=True)


def parse_letter_no(letter_no: pd.Series) -> pd.DataFrame:
    """LN/MP18129/2024-2025/3 -> mp_code=18129, fy_start_year=2024,
    fy_end_year=2025, letter_seq=3. Non-matching values become NaN rather
    than raising, since malformed/missing letter numbers are themselves a
    signal (see the sequencing-integrity rule in Phase 1).

    Real records contain stray whitespace/tab characters mid-string (e.g.
    "LN/\t MP319/2024-2025/32") - strip all whitespace before matching so
    that isn't misread as a broken letter number."""
    cleaned = letter_no.str.replace(r"\s+", "", regex=True)
    extracted = cleaned.str.extract(LETTER_NO_RE)
    extracted.columns = ["mp_code", "fy_start_year", "fy_end_year", "letter_seq"]
    for col in extracted.columns:
        extracted[col] = pd.to_numeric(extracted[col], errors="coerce")
    return extracted


def fiscal_year_bounds(fy_start_year: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Indian fiscal year runs 1-Apr to 31-Mar. Returns (fy_start_date,
    fy_end_date) for the fiscal year named in a work's own LETTER_NO."""
    fy_start_date = pd.to_datetime(
        fy_start_year.astype("Int64").astype(str) + "-04-01", errors="coerce"
    )
    fy_end_date = pd.to_datetime(
        (fy_start_year + 1).astype("Int64").astype(str) + "-03-31", errors="coerce"
    )
    return fy_start_date, fy_end_date


def containing_fy_end(actual_end_date: pd.Series) -> pd.Series:
    """The 31-Mar that closes out the fiscal year actual_end_date falls in -
    used for the fiscal-year-dumping rule, independent of which FY the
    LETTER_NO itself was issued under (a work can slip into the next FY)."""
    year = actual_end_date.dt.year
    is_before_apr = actual_end_date.dt.month < 4
    fy_close_year = year.where(is_before_apr, year + 1)
    return pd.to_datetime(fy_close_year.astype("Int64").astype(str) + "-03-31", errors="coerce")


def normalize_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.upper()


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["actual_end_date"] = pd.to_datetime(df["ACTUAL_END_DATE"], format="%d-%b-%Y", errors="coerce")

    letter_parts = parse_letter_no(df["LETTER_NO"].astype("string"))
    df = pd.concat([df, letter_parts], axis=1)

    fy_start_date, _fy_end_from_letter = fiscal_year_bounds(df["fy_start_year"])
    # Legacy fiscal-year proxy, not an observed sanction date or a guaranteed
    # bound. Canonical ingestion replaces this duration with the real joined
    # sanction date and labels any fallback explicitly.
    df["sanction_date_proxy"] = fy_start_date
    df["duration_days"] = (df["actual_end_date"] - df["sanction_date_proxy"]).dt.days

    fy_close = containing_fy_end(df["actual_end_date"])
    df["days_to_fy_end"] = (fy_close - df["actual_end_date"]).dt.days

    df["has_images"] = df["image_count"].fillna(0) > 0

    norm_targets = {
        "STATE_NAME": "state_norm",
        "IDA_NAME": "ida_norm",
        "MP_NAME": "mp_norm",
        "WORK_CATEGORY": "category_norm",
    }
    for src_col, out_col in norm_targets.items():
        df[out_col] = normalize_text(df[src_col])

    # peer group used by the cost-per-unit outlier rule (Phase 1) and the
    # NLP-derived cost baseline (Phase 4) - same category, same state, since
    # unit costs vary by region.
    df["category_state_key"] = df["category_norm"] + " | " + df["state_norm"]

    return df


def main() -> None:
    raw = load_raw_works()
    print(f"loaded {len(raw)} rows from {raw['_source_csv'].nunique()} constituency CSVs")

    enriched = engineer_features(raw)

    n_bad_letter = enriched["mp_code"].isna().sum()
    n_bad_date = enriched["actual_end_date"].isna().sum()
    print(f"  {n_bad_letter} rows with unparseable LETTER_NO")
    print(f"  {n_bad_date} rows with unparseable ACTUAL_END_DATE")
    print(f"  {(~enriched['has_images']).sum()} rows with zero images")
    print(f"  states covered: {enriched['state_norm'].nunique()}")
    print(f"  category/state peer groups: {enriched['category_state_key'].nunique()}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    enriched.to_parquet(OUT_PATH, index=False)
    print(f"wrote {OUT_PATH} ({len(enriched)} rows, {len(enriched.columns)} columns)")


if __name__ == "__main__":
    main()
