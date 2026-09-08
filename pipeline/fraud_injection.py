"""
Synthetic fraud-injection benchmark harness.

Plants fabricated work records shaped like real CAG-documented MPLADS fraud
patterns (see memory/cag_fraud_patterns.md) into a copy of the real corpus,
so the anomaly-detection pipeline's recall can be measured once it exists.
1-2 instances per detector family, covering: rule-based flags, Isolation
Forest multivariate outliers, Benford's Law digit-distribution fabrication,
and CV photo-reuse/category-mismatch (exact duplicate, edited near-duplicate,
wrong-category photo).

Isolation guarantee (do not weaken): the REAL scraped data is never modified.
- Real per-constituency `works_with_images.csv` files: untouched.
- Real `mplads_india/_consolidated/master_works.parquet`: untouched.
- Output goes only to `mplads_india/_consolidated/eval_with_injected_fraud.parquet`
  (real + injected rows, ordered position carries no signal) and `eval/`
  (ground truth — ids, pattern, and why each row is fraudulent). The eval
  parquet itself carries no fraud-flag column, so a model trained/scored on
  it cannot read off the answer; only cross-referencing against `eval/`
  reveals which WORK_IDs were planted.
- Injected photo attachments (exact/near-duplicate/mismatched) are written
  as new files (900000001_1.pdf-style names, never colliding with real
  WORK_RECOMMENDATION_DTL_IDs) inside the same real constituency folders a
  future image pipeline will walk, so directory-walk-based discovery finds
  them the same way it finds real attachments.

Usage:
    python -m pipeline.fraud_injection
"""

import io
import json
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

import fitz  # pymupdf
import pandas as pd
from PIL import Image, ImageEnhance

from pipeline.consolidate import (
    LETTER_NO_RE,
    OUT_DIR,
    engineer_features,
    load_raw_works,
)

SEED = 20260908
RNG = random.Random(SEED)

EVAL_OUT_PATH = OUT_DIR / "eval_with_injected_fraud.parquet"
GROUND_TRUTH_DIR = Path("eval")
GROUND_TRUTH_JSON = GROUND_TRUTH_DIR / "fraud_ground_truth.json"
GROUND_TRUTH_CSV = GROUND_TRUTH_DIR / "fraud_ground_truth.csv"

# Real WORK_ID / WORK_RECOMMENDATION_DTL_ID max is ~198k and ~300k
# respectively as of the 2026-09-08 partial India scrape. 900000001+ can
# never collide with a real scraped id.
_id_counter = [900000001]


def next_id() -> int:
    val = _id_counter[0]
    _id_counter[0] += 1
    return val


RAW_COLUMNS = [
    "WORK_CATEGORY", "ACTIVITY_NAME", "STATE_NAME", "IDA_NAME",
    "WORK_DESCRIPTION", "MP_NAME", "FLAG", "CONSTITUENCY_ID", "LETTER_NO",
    "ACTUAL_AMOUNT", "Sno", "CONSTITUENCY", "ACTUAL_END_DATE",
    "WORK_RECOMMENDATION_DTL_ID", "FILE_STATUS", "WORK_ID", "ATTACH_ID",
    "AVERAGE_RATING", "local_image_filenames", "image_count", "_source_csv",
]


def fmt_date(d: date) -> str:
    return d.strftime("%d-%b-%Y")


def parse_letter_no(letter_no: str):
    cleaned = "".join(letter_no.split())
    m = LETTER_NO_RE.match(cleaned)
    if not m:
        return None
    mp_code, fy_start, fy_end, seq = m.groups()
    return int(mp_code), int(fy_start), int(fy_end), int(seq)


def clone(row: pd.Series) -> dict:
    return {c: row[c] for c in RAW_COLUMNS}


def constituency_dir(row: pd.Series) -> Path:
    return Path(row["_source_csv"]).parent


def new_ids(row: dict) -> None:
    """Assign fresh, out-of-band ids to an already-cloned raw row dict."""
    wid = next_id()
    row["WORK_ID"] = wid
    row["WORK_RECOMMENDATION_DTL_ID"] = wid
    row["Sno"] = wid


def attach_pdf(row: dict, pdf_bytes: bytes) -> None:
    """Write a new attachment PDF for an injected row and wire up the
    local_image_filenames / image_count / ATTACH_ID / FILE_STATUS fields
    the way a real completed-with-photo work would have them set."""
    dest_dir = Path(row["_source_csv"]).parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{row['WORK_RECOMMENDATION_DTL_ID']}_1.pdf"
    (dest_dir / filename).write_bytes(pdf_bytes)
    row["local_image_filenames"] = filename
    row["image_count"] = 1
    row["ATTACH_ID"] = float(row["WORK_RECOMMENDATION_DTL_ID"])
    row["FILE_STATUS"] = True


def extract_first_image(pdf_path: Path) -> tuple[bytes, int, int]:
    doc = fitz.open(pdf_path)
    for page in doc:
        imgs = page.get_images(full=True)
        if imgs:
            xref = imgs[0][0]
            base = doc.extract_image(xref)
            return base["image"], base["width"], base["height"]
    raise ValueError(f"no embedded image found in {pdf_path}")


def make_single_image_pdf(jpeg_bytes: bytes, width: int, height: int) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_image(page.rect, stream=jpeg_bytes)
    return doc.tobytes()


def edit_image(jpeg_bytes: bytes) -> bytes:
    """Mild, realistic edits: what someone re-submitting an old photo would
    do without meaning to defeat forensics - crop a few %, nudge
    brightness/contrast, tiny rotation."""
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    w, h = img.size
    crop_pct = RNG.uniform(0.02, 0.05)
    dx, dy = int(w * crop_pct), int(h * crop_pct)
    img = img.crop((dx, dy, w - dx, h - dy))
    img = ImageEnhance.Brightness(img).enhance(RNG.uniform(0.85, 1.15))
    img = ImageEnhance.Contrast(img).enhance(RNG.uniform(0.9, 1.1))
    angle = RNG.uniform(-2.5, 2.5)
    img = img.rotate(angle, expand=False, fillcolor=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=RNG.randint(80, 92))
    return buf.getvalue()


def find_real_pdf(raw: pd.DataFrame, rng: random.Random) -> tuple[Path, pd.Series]:
    """Pick a random real row that actually has a downloaded attachment and
    return (its first pdf path, the row)."""
    has_pdf = raw[raw["local_image_filenames"].notna()]
    for _ in range(200):
        row = has_pdf.sample(1, random_state=rng.randint(0, 2**31)).iloc[0]
        fname = str(row["local_image_filenames"]).split(";")[0]
        p = Path(row["_source_csv"]).parent / fname
        if p.exists():
            return p, row
    raise RuntimeError("could not find a real, existing attachment PDF to clone from")


# ---------------------------------------------------------------------------
# Pattern generators. Each returns (list_of_raw_row_dicts, list_of_ground_truth_dicts)
# ---------------------------------------------------------------------------

def pattern_structuring(raw: pd.DataFrame) -> tuple[list, list]:
    """Rule 1: sub-10L structuring - amount parked just under the
    Rs.10,00,000 sanction/scrutiny threshold."""
    rows, gts = [], []
    pool = raw[raw["category_norm"] == "NORMAL/OTHERS"] if "category_norm" in raw else raw
    for amount in (999900.0, 995500.0):
        base = pool.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(base)
        new_ids(r)
        r["ACTUAL_AMOUNT"] = amount
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "sub_10L_structuring",
            "detector_target": "rule:sub_10L_structuring",
            "cloned_from_work_id": int(base["WORK_ID"]),
            "description": f"ACTUAL_AMOUNT={amount} parked just under the Rs.10,00,000 threshold",
        })
    return rows, gts


def pattern_missing_images(raw: pd.DataFrame) -> tuple[list, list]:
    """Rule 3: marked complete, zero photographic evidence."""
    rows, gts = [], []
    for _ in range(2):
        base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(base)
        new_ids(r)
        r["FILE_STATUS"] = True
        r["local_image_filenames"] = None
        r["image_count"] = 0
        r["ATTACH_ID"] = None
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "missing_images_on_completed_work",
            "detector_target": "rule:missing_images",
            "cloned_from_work_id": int(base["WORK_ID"]),
            "description": "FILE_STATUS=complete but image_count=0 / no attachment",
        })
    return rows, gts


def pattern_cost_outlier(raw: pd.DataFrame) -> tuple[list, list]:
    """Rule 4 / Isolation Forest: cost-per-unit inflation within a
    category+state peer group - CAG 'excess payment for substandard
    materials' pattern."""
    rows, gts = [], []
    key = "NORMAL/OTHERS | BIHAR"
    group = raw[raw["category_state_key"] == key]
    median = group["ACTUAL_AMOUNT"].median()
    for mult in (9.0, 7.5):
        base = group.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(base)
        new_ids(r)
        inflated = round(median * mult, -3)
        r["ACTUAL_AMOUNT"] = inflated
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "cost_per_unit_inflation",
            "detector_target": "rule:cost_outlier / isolation_forest",
            "cloned_from_work_id": int(base["WORK_ID"]),
            "description": f"ACTUAL_AMOUNT={inflated} vs peer-group ({key}) median {median:.0f} ({mult}x)",
        })
    return rows, gts


def pattern_short_gap(raw: pd.DataFrame) -> tuple[list, list]:
    """Rule 5: implausibly fast sanction-to-completion for real infra work."""
    rows, gts = [], []
    for days in (4, 9):
        base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(base)
        new_ids(r)
        parsed = parse_letter_no(str(base["LETTER_NO"]))
        fy_start_year = parsed[1] if parsed else 2024
        r["LETTER_NO"] = f"LN/MP{parsed[0] if parsed else 18001}/{fy_start_year}-{fy_start_year+1}/{next_id() % 90 + 1}"
        r["ACTUAL_END_DATE"] = fmt_date(date(fy_start_year, 4, 1) + timedelta(days=days))
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "implausibly_short_sanction_to_completion_gap",
            "detector_target": "rule:duration_too_short",
            "cloned_from_work_id": int(base["WORK_ID"]),
            "description": f"duration_days~={days} (fiscal-year-start proxy to completion)",
        })
    return rows, gts


def pattern_fy_end_dumping(raw: pd.DataFrame) -> tuple[list, list]:
    """Rule 2: cluster of one MP/IDA's completions crammed into the last
    days of the fiscal year."""
    rows, gts = [], []
    base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
    ids = []
    for i in range(5):
        r = clone(base)
        new_ids(r)
        r["ACTUAL_END_DATE"] = fmt_date(date(2025, 3, 22 + i))
        r["WORK_DESCRIPTION"] = f"{base['WORK_DESCRIPTION']} (batch {i+1})"
        rows.append(r)
        ids.append(r["WORK_ID"])
    gts.append({
        "work_id": ids[0], "cluster_work_ids": ids, "pattern": "fiscal_year_end_dumping_cluster",
        "detector_target": "rule:fy_end_dumping_share",
        "cloned_from_work_id": int(base["WORK_ID"]),
        "description": f"5 works by {base['MP_NAME']} all completed 22-26 Mar 2025 (last days of FY24-25)",
    })
    return rows, gts


def pattern_cross_year_duplicate(raw: pd.DataFrame) -> tuple[list, list]:
    """CAG case: same asset ('renovation of Panchayat building') claimed
    again a year later. NLP cross-year duplicate-description detector."""
    rows, gts = [], []
    for _ in range(2):
        base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        parsed = parse_letter_no(str(base["LETTER_NO"]))
        r = clone(base)
        new_ids(r)
        if parsed:
            mp_code, fy_start, fy_end, seq = parsed
            r["LETTER_NO"] = f"LN/MP{mp_code}/{fy_start+1}-{fy_end+1}/{seq}"
        try:
            end = pd.to_datetime(base["ACTUAL_END_DATE"], format="%d-%b-%Y")
            r["ACTUAL_END_DATE"] = fmt_date((end + pd.DateOffset(years=1)).date())
        except Exception:
            r["ACTUAL_END_DATE"] = fmt_date(date(2025, 6, 15))
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "cross_year_duplicate_asset_claim",
            "detector_target": "nlp:cross_year_description_dedup",
            "cloned_from_work_id": int(base["WORK_ID"]),
            "description": "identical WORK_DESCRIPTION/IDA/MP re-claimed one fiscal year later",
        })
    return rows, gts


def pattern_nonstandard_ida(raw: pd.DataFrame) -> tuple[list, list]:
    """CAG case: funds routed through a trust/cooperative society instead
    of the prescribed District Authority."""
    rows, gts = [], []
    fake_idas = [
        "Sri Venkateswara Charitable Trust",
        "Jan Kalyan Sewa Cooperative Society Ltd.",
    ]
    for fake_ida in fake_idas:
        base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(base)
        new_ids(r)
        r["IDA_NAME"] = fake_ida
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "non_standard_implementing_agency",
            "detector_target": "rule:ida_entity_type_classifier",
            "cloned_from_work_id": int(base["WORK_ID"]),
            "description": f"IDA_NAME='{fake_ida}' (trust/society, not District Collector/Municipal Corp/Zilla Parishad)",
        })
    return rows, gts


def pattern_broken_sequencing(raw: pd.DataFrame) -> tuple[list, list]:
    """CAG case: anticipatory/unauthorized sanctioning - no valid
    recommendation letter on record, or a letter dated after completion."""
    rows, gts = [], []

    base1 = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
    r1 = clone(base1)
    new_ids(r1)
    r1["LETTER_NO"] = ""
    rows.append(r1)
    gts.append({
        "work_id": r1["WORK_ID"], "pattern": "broken_sequencing_missing_letter",
        "detector_target": "rule:letter_no_unparseable",
        "cloned_from_work_id": int(base1["WORK_ID"]),
        "description": "LETTER_NO blank - no recommendation letter on record",
    })

    base2 = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
    r2 = clone(base2)
    new_ids(r2)
    r2["LETTER_NO"] = "LN/MP18001/2026-2027/1"
    r2["ACTUAL_END_DATE"] = fmt_date(date(2025, 5, 1))
    rows.append(r2)
    gts.append({
        "work_id": r2["WORK_ID"], "pattern": "broken_sequencing_future_dated_letter",
        "detector_target": "rule:sanction_date_after_completion",
        "cloned_from_work_id": int(base2["WORK_ID"]),
        "description": "LETTER_NO fiscal year 2026-2027 issued after ACTUAL_END_DATE 2025-05-01 (completed before sanctioned)",
    })
    return rows, gts


def pattern_benford_violation(raw: pd.DataFrame) -> tuple[list, list]:
    """Benford's Law: 30 fabricated amounts for one IDA, hand-picked round
    numbers concentrated on non-1 leading digits instead of amounts drawn
    from real invoices (which skew toward leading digit 1)."""
    rows, gts = [], []
    ida_pool = raw[raw["IDA_NAME"].str.contains("DISTRICT", case=False, na=False)]
    target_ida_row = ida_pool.sample(1, random_state=7).iloc[0]
    target_ida = target_ida_row["IDA_NAME"]

    human_round_amounts = [
        550000, 600000, 650000, 700000, 750000, 800000,
        850000, 900000, 950000, 999999,
    ]
    ids = []
    for i in range(30):
        base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(base)
        new_ids(r)
        r["IDA_NAME"] = target_ida
        r["STATE_NAME"] = target_ida_row["STATE_NAME"]
        r["ACTUAL_AMOUNT"] = float(RNG.choice(human_round_amounts))
        rows.append(r)
        ids.append(r["WORK_ID"])
    gts.append({
        "work_id": ids[0], "cluster_work_ids": ids, "pattern": "benford_law_violation_cluster",
        "detector_target": "benford:leading_digit_chi_square_per_ida",
        "cloned_from_work_id": None,
        "description": (
            f"30 works fabricated for IDA='{target_ida}' using hand-picked round amounts "
            "concentrated on leading digits 5-9 instead of a natural invoice-driven "
            "leading-digit distribution (real data skews toward leading digit 1)"
        ),
    })
    return rows, gts


def pattern_rule163_split(raw: pd.DataFrame) -> tuple[list, list]:
    """GFR 2017 Rule 163: same work split into piecemeal purchases, each
    individually under the sanction threshold, summing well over it."""
    rows, gts = [], []
    themes = [
        "Construction of CC Road from {a} to {b}",
        "Repair and Renovation of Community Hall at {a}",
    ]
    for theme in themes:
        base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        parsed = parse_letter_no(str(base["LETTER_NO"]))
        mp_code, fy_start = (parsed[0], parsed[1]) if parsed else (18001, 2024)
        ids = []
        for i in range(3):
            r = clone(base)
            new_ids(r)
            r["WORK_DESCRIPTION"] = theme.format(a="Junction Point", b="Village School") + f" - Phase {i+1}"
            r["ACTUAL_AMOUNT"] = round(RNG.uniform(380000, 450000), -2)
            r["LETTER_NO"] = f"LN/MP{mp_code}/{fy_start}-{fy_start+1}/{100+i}"
            r["ACTUAL_END_DATE"] = fmt_date(date(fy_start, 8, 5 + i * 3))
            rows.append(r)
            ids.append(r["WORK_ID"])
        total = sum(rr["ACTUAL_AMOUNT"] for rr in rows[-3:])
        gts.append({
            "work_id": ids[0], "cluster_work_ids": ids, "pattern": "rule163_threshold_splitting",
            "detector_target": "nlp:near_identical_description_cluster_sum",
            "cloned_from_work_id": int(base["WORK_ID"]),
            "description": f"3 near-identical descriptions from same MP within days, each <10L, cluster sum={total:.0f}",
        })
    return rows, gts


def pattern_exact_image_duplicate(raw: pd.DataFrame) -> tuple[list, list]:
    """CV 3a: the exact same completion photo reused to prove two
    different works."""
    rows, gts = [], []
    for _ in range(2):
        src_pdf, src_row = find_real_pdf(raw, RNG)
        target_base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(target_base)
        new_ids(r)
        attach_pdf(r, src_pdf.read_bytes())
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "exact_image_duplicate_reuse",
            "detector_target": "cv:phash_exact_duplicate",
            "cloned_from_work_id": int(target_base["WORK_ID"]),
            "reused_photo_from_work_id": int(src_row["WORK_ID"]),
            "description": f"attachment is a byte-for-byte copy of WORK_ID={int(src_row['WORK_ID'])}'s photo",
        })
    return rows, gts


def pattern_near_duplicate_image(raw: pd.DataFrame) -> tuple[list, list]:
    """CV 3a: same physical photo, lightly cropped/brightness-adjusted/
    rotated before resubmission - the harder confirmation-step case."""
    rows, gts = [], []
    for _ in range(2):
        src_pdf, src_row = find_real_pdf(raw, RNG)
        jpeg_bytes, w, h = extract_first_image(src_pdf)
        edited = edit_image(jpeg_bytes)
        edited_pdf = make_single_image_pdf(edited, w, h)

        target_base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(target_base)
        new_ids(r)
        attach_pdf(r, edited_pdf)
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "near_duplicate_edited_image_reuse",
            "detector_target": "cv:phash_near_duplicate + dinov2_embedding_cluster",
            "cloned_from_work_id": int(target_base["WORK_ID"]),
            "reused_photo_from_work_id": int(src_row["WORK_ID"]),
            "description": (
                f"attachment is WORK_ID={int(src_row['WORK_ID'])}'s photo, cropped ~2-5%, "
                "brightness/contrast nudged, rotated <=2.5 deg"
            ),
        })
    return rows, gts


def pattern_category_mismatch_image(raw: pd.DataFrame) -> tuple[list, list]:
    """CV 3c: the submitted photo doesn't depict the claimed work
    category at all (wrong invoice/old stock photo attached)."""
    rows, gts = [], []
    mismatched_descriptions = [
        ("Repair and Renovation", "Construction of CC Road from Bus Stand to Panchayat Office"),
        ("Normal/Others", "Purchase of Water Purifier (RO plant) for Govt. Primary School"),
    ]
    for category, description in mismatched_descriptions:
        src_pdf, src_row = find_real_pdf(raw, RNG)
        target_base = raw.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        r = clone(target_base)
        new_ids(r)
        r["WORK_CATEGORY"] = category
        r["WORK_DESCRIPTION"] = description
        r["ACTIVITY_NAME"] = description[:60]
        attach_pdf(r, src_pdf.read_bytes())
        rows.append(r)
        gts.append({
            "work_id": r["WORK_ID"], "pattern": "category_mismatch_photo",
            "detector_target": "cv:clip_zero_shot_category_similarity",
            "cloned_from_work_id": int(target_base["WORK_ID"]),
            "reused_photo_from_work_id": int(src_row["WORK_ID"]),
            "description": (
                f"claimed work='{description}' but attached photo is WORK_ID="
                f"{int(src_row['WORK_ID'])}'s (activity='{src_row['ACTIVITY_NAME']}') unrelated photo"
            ),
        })
    return rows, gts


PATTERNS = [
    pattern_structuring,
    pattern_missing_images,
    pattern_cost_outlier,
    pattern_short_gap,
    pattern_fy_end_dumping,
    pattern_cross_year_duplicate,
    pattern_nonstandard_ida,
    pattern_broken_sequencing,
    pattern_benford_violation,
    pattern_rule163_split,
    pattern_exact_image_duplicate,
    pattern_near_duplicate_image,
    pattern_category_mismatch_image,
]


def main() -> None:
    raw = load_raw_works()
    raw_enriched = engineer_features(raw)  # gives category_state_key/category_norm/IDA text used by pattern picks
    print(f"loaded {len(raw)} real rows to inject fraud on top of")

    all_new_rows: list[dict] = []
    all_ground_truth: list[dict] = []
    for pattern_fn in PATTERNS:
        rows, gts = pattern_fn(raw_enriched)
        all_new_rows.extend(rows)
        all_ground_truth.extend(gts)
        print(f"  {pattern_fn.__name__}: +{len(rows)} rows, {len(gts)} ground-truth entries")

    injected_raw_df = pd.DataFrame(all_new_rows)[RAW_COLUMNS]
    combined_raw = pd.concat([raw, injected_raw_df], ignore_index=True)

    # Shuffle so injected rows aren't trivially identifiable by position.
    combined_raw = combined_raw.sample(frac=1.0, random_state=SEED).reset_index(drop=True)

    combined_enriched = engineer_features(combined_raw)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    combined_enriched.to_parquet(EVAL_OUT_PATH, index=False)
    print(f"\nwrote {EVAL_OUT_PATH} "
          f"({len(combined_enriched)} rows = {len(raw)} real + {len(injected_raw_df)} injected)")

    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    with open(GROUND_TRUTH_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "seed": SEED,
            "eval_dataset": str(EVAL_OUT_PATH),
            "n_real_rows": len(raw),
            "n_injected_rows": len(injected_raw_df),
            "injected_work_ids": sorted(int(x) for x in injected_raw_df["WORK_ID"]),
            "patterns": all_ground_truth,
        }, f, indent=2, default=str)

    gt_flat = []
    for g in all_ground_truth:
        ids = g.get("cluster_work_ids", [g["work_id"]])
        for wid in ids:
            gt_flat.append({
                "work_id": int(wid),
                "pattern": g["pattern"],
                "detector_target": g["detector_target"],
                "cluster_id": g["work_id"] if "cluster_work_ids" in g else None,
                "description": g["description"],
            })
    pd.DataFrame(gt_flat).to_csv(GROUND_TRUTH_CSV, index=False)

    print(f"wrote {GROUND_TRUTH_JSON} and {GROUND_TRUTH_CSV} "
          f"({len(gt_flat)} injected WORK_IDs across {len(all_ground_truth)} pattern instances)")
    print("\nNOTE: eval parquet has no fraud-flag column - only eval/fraud_ground_truth.*"
          " tells you which WORK_IDs are synthetic. Do not join them back before scoring a model.")


if __name__ == "__main__":
    main()
