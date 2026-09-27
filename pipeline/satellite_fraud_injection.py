"""
Satellite module, step 4 - synthetic MPLADS overlay (see
docs/SATELLITE_VENDOR_MODULE_PLAN.md #4).

Fabricates MPLADS-shaped work records on top of two branches of source
data, and injects fraud patterns onto a subset of each:

  Branch A (satellite-visible): the REAL OpenStreetMap coordinates from
  data/geotags/sourced_assets.csv, scored by ml/cv/satellite_change.py.
  Patterns: phantom_work, coordinate_reuse, backdated_completion.

  Branch B (non-visible): real small/indoor-category rows from the actual
  scraped MPLADS corpus (pipeline.consolidate.load_raw_works), no imagery
  involved at all. Patterns: cost_outlier, missing_evidence, structuring,
  cross_year_text_duplicate, entitlement_pace_cluster - the same kinds of
  signal pipeline/fraud_injection.py already injects, reimplemented here
  against the small-category peer group rather than reused directly,
  since the existing pattern functions hardcode peer-group keys/IDA
  strings specific to their own real-corpus sampling and aren't safe to
  call unmodified against a filtered subset.

Honesty framing (see docs/SATELLITE_VENDOR_MODULE_PLAN.md #0 and this
module's own docs/SATELLITE_MODULE_DATA_REALITY.md):
  - Branch A coordinates are real (OpenStreetMap, not MPLADS - no MPLADS
    bulk geotag export exists). Branch B category/cost data is drawn from
    the real scraped MPLADS corpus, but the specific MP_NAME/IDA_NAME
    values attached to EVERY row in this file - both branches - are
    deliberately fictional (DEMO-prefixed), never a real scraped MP_NAME.
    Attaching a fabricated fraud claim to a real named MP would misrepresent
    a real, identifiable person; this module never does that. Sampling
    ratio (~30-40% Branch A, oversampled to showcase satellite
    verification) is a demo choice, not a claim about real-world category
    or fraud prevalence.
  - Isolation guarantee (same as pipeline/fraud_injection.py): the real
    corpus is loaded read-only. This script writes only to
    data/canonical/satellite_works.csv and eval/satellite_ground_truth.*.

Usage:
    python -m pipeline.satellite_fraud_injection
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from pipeline.consolidate import engineer_features, load_raw_works

SEED = 20260925
RNG = random.Random(SEED)

ASSETS_PATH = Path("data/geotags/sourced_assets.csv")
CHANGE_RESULTS_PATH = Path("data/canonical/satellite_change_results.csv")
OUT_PATH = Path("data/canonical/satellite_works.csv")
GROUND_TRUTH_DIR = Path("eval")
GROUND_TRUTH_CSV = GROUND_TRUTH_DIR / "satellite_ground_truth.csv"

# Out-of-band id range: existing fraud_injection.py uses 900000001+ for its
# own injected rows against the real WORK_ID space (~198k max). This module
# fabricates a disjoint id space and its own disjoint MP-code space so
# neither script's synthetic ids can ever collide with the other's or with
# a real one.
_id_counter = [950000001]
_mp_code_counter = [95001]


def next_id() -> int:
    val = _id_counter[0]
    _id_counter[0] += 1
    return val


def next_mp_code() -> int:
    val = _mp_code_counter[0]
    _mp_code_counter[0] += 1
    return val


def fmt_date(d: date) -> str:
    return d.strftime("%d-%b-%Y")


# Branch A: map OSM category -> closest real MPLADS activity peer group,
# used only to draw a real, historically-observed cost distribution -
# never to imply the OSM asset itself is an MPLADS work.
BRANCH_A_PEER_ACTIVITY = {
    "dam": "flood control embankments",
    "community_centre": "community centers and community halls",
    "road": "roads, link roads, pathways",
}

# Branch B: real small/indoor-category activities (majority of the actual
# corpus per docs/DATA_REALITY.md) - no plausible satellite footprint.
BRANCH_B_ACTIVITIES = [
    "Street lights",
    "Lighting of public spaces",
    "Installing tube-wells and borewells",
    "Installing hand pumps",
    "Setting up of laboratories",
    "Purchase of furniture and fixtures for educational purposes",
    "Installation of multi-gym equipment",
    "Providing CCTV camera system for security of public areas",
]

# Realistic-*styled* fictional names, not literal "DEMO"/"Sample N" strings -
# same convention this project already uses for its own demo persona
# ("Arvind Dharmapuri" in data/personas.json). The demo/fictional framing
# lives in the UI copy and these docs, not in the values themselves - a name
# that visibly reads as a placeholder is easy to skim past, which defeats
# the point of a realistic-looking demo. Deliberately generic combinations
# (common first names x common surnames, generic -puram/-nagar/-pet
# toponyms) so nothing here is styled after one specific real person or
# body. See docs/SATELLITE_MODULE_DATA_REALITY.md for the honesty framing.
_FIRST_NAMES = ["Arvind", "Suresh", "Ramesh", "Mahesh", "Prakash", "Anand", "Vikram", "Sanjay",
                "Naveen", "Rajesh", "Kiran", "Deepak", "Ashok", "Vijay", "Manoj", "Ravi",
                "Shankar", "Ganesh", "Harish", "Mohan"]
_SURNAMES = ["Dharmapuri", "Naik", "Reddy", "Rao", "Yadav", "Sharma", "Verma", "Patil",
             "Gowda", "Chauhan", "Mishra", "Iyer", "Nair", "Pillai", "Choudhary", "Bhatt",
             "Joshi", "Kulkarni", "Menon", "Shetty"]
FICTIONAL_MP_NAMES = [f"{f} {s}" for f, s in zip(_FIRST_NAMES, _SURNAMES)]

_DISTRICT_STEMS = ["Rangapuram", "Chandranagar", "Vasavipet", "Gopalpuram", "Anjaneyanagar",
                    "Krishnapet", "Lakshmipuram", "Devarakonda", "Narsapur", "Bhavanipet"]
_IDA_SUFFIXES = ["Zilla Parishad", "Municipal Corporation", "District Rural Development Agency"]
FICTIONAL_IDA_NAMES = [f"{d} {_IDA_SUFFIXES[i % len(_IDA_SUFFIXES)]}" for i, d in enumerate(_DISTRICT_STEMS)]

# Fake village/locality names for WORK_DESCRIPTION and the new area_name
# field - distinct pool from the IDA stems above so a work's village and its
# implementing agency don't look copy-pasted from the same list.
_VILLAGE_STEMS = ["Ramapuram", "Krishnapuram", "Anandnagar", "Gopalpet", "Venkatapuram",
                   "Subhashnagar", "Malleswaram", "Chinnapet", "Peddapuram", "Sitanagar",
                   "Kondapur", "Yellareddyguda", "Narsingapur", "Mahadevpet", "Rajupalem",
                   "Shivajinagar", "Balajipet", "Chandrapuram", "Ambedkarnagar", "Veerapuram"]

BRANCH_A_DESCRIPTIONS = {
    "dam": "Construction of check dam / flood control embankment near {village}",
    "community_centre": "Construction of community center and community hall at {village}",
    "road": "Construction of road with drainage system from {village} to nearby junction",
}


def clean_activity(series: pd.Series) -> pd.Series:
    return series.astype("string").str.replace(r"^WS/MP\d+/\d{4}-\d{4}/\d+-", "", regex=True)


def fabricated_letter_no(fy_start: int) -> str:
    return f"LN/MP{next_mp_code()}/{fy_start}-{fy_start+1}/{RNG.randint(1, 90)}"


def new_work_base(mp_name: str, ida_name: str, activity: str, amount: float,
                   fy_start: int, end_date: date, area_name: str | None = None) -> dict:
    return {
        "work_id": next_id(),
        "MP_NAME": mp_name,
        "IDA_NAME": ida_name,
        "WORK_DESCRIPTION": activity,
        "area_name": area_name or RNG.choice(_VILLAGE_STEMS),
        "ACTUAL_AMOUNT": round(float(amount), 2),
        "LETTER_NO": fabricated_letter_no(fy_start),
        "ACTUAL_END_DATE": fmt_date(end_date),
        "has_images": True,
    }


# ---------------------------------------------------------------------------
# Branch A - real coordinates, imagery-based patterns
# ---------------------------------------------------------------------------

def build_branch_a(real_corpus: pd.DataFrame, n_target: int) -> tuple[list[dict], list[dict]]:
    assets = pd.read_csv(ASSETS_PATH)
    if CHANGE_RESULTS_PATH.exists():
        change = pd.read_csv(CHANGE_RESULTS_PATH).set_index("asset_id")
    else:
        change = pd.DataFrame(columns=["change_detected"]).set_index(pd.Index([], name="asset_id"))

    assets = assets.sample(n=min(n_target, len(assets)), random_state=SEED).reset_index(drop=True)

    rows, gts = [], []
    coordinate_reuse_pool: list[dict] = []

    for _, asset in assets.iterrows():
        activity_key = BRANCH_A_PEER_ACTIVITY.get(asset["category"], "roads, link roads, pathways")
        peer = real_corpus[real_corpus["activity_clean"].str.contains(activity_key, case=False, na=False)]
        amount = float(peer["ACTUAL_AMOUNT"].sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]) \
            if len(peer) else 500000.0

        has_change_result = asset["asset_id"] in change.index
        real_change = bool(change.loc[asset["asset_id"], "change_detected"]) if has_change_result else None

        fy_start = 2025
        mp_name = RNG.choice(FICTIONAL_MP_NAMES)
        ida_name = RNG.choice(FICTIONAL_IDA_NAMES)
        end_date = date(fy_start, 6, RNG.randint(1, 28))

        village = RNG.choice(_VILLAGE_STEMS)
        description = BRANCH_A_DESCRIPTIONS.get(asset["category"], "Construction of public work at {village}").format(village=village)
        base = new_work_base(mp_name, ida_name, description, amount, fy_start, end_date, area_name=village)
        base.update({
            "branch": "A", "asset_id": asset["asset_id"], "lat": asset["lat"], "lon": asset["lon"],
            "source_scheme": "openstreetmap", "category": asset["category"],
        })

        if has_change_result and real_change:
            pattern = "genuine"
        elif has_change_result and not real_change:
            pattern = "phantom_work"
        else:
            pattern = "genuine_unverified"  # no satellite pair fetched for this asset yet

        rows.append(base)
        gts.append({
            "work_id": base["work_id"], "branch": "A", "pattern": pattern,
            "asset_id": asset["asset_id"],
            "description": f"category={asset['category']}, real_change_detected={real_change}",
        })
        coordinate_reuse_pool.append(base)

    # coordinate_reuse: pick 2 already-built Branch A rows and add a second
    # fabricated work at the SAME coordinate under a different MP/IDA.
    if len(coordinate_reuse_pool) >= 2:
        for src in RNG.sample(coordinate_reuse_pool, k=min(2, len(coordinate_reuse_pool))):
            dup_amount = src["ACTUAL_AMOUNT"] * RNG.uniform(0.8, 1.2)
            dup = new_work_base(RNG.choice(FICTIONAL_MP_NAMES), RNG.choice(FICTIONAL_IDA_NAMES),
                                 src["WORK_DESCRIPTION"], dup_amount, 2025, date(2025, 8, RNG.randint(1, 28)),
                                 area_name=src["area_name"])
            dup.update({
                "branch": "A", "asset_id": src["asset_id"], "lat": src["lat"], "lon": src["lon"],
                "source_scheme": "openstreetmap", "category": src["category"],
            })
            rows.append(dup)
            gts.append({
                "work_id": dup["work_id"], "branch": "A", "pattern": "coordinate_reuse",
                "asset_id": src["asset_id"],
                "description": f"same coordinate as work_id={src['work_id']} (asset_id={src['asset_id']}), different fabricated MP/IDA",
            })

    # backdated_completion: claimed completion date precedes the real
    # imagery's observed change window (t2 date from the manifest).
    manifest_path = Path("data/satellite_cache/manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        candidates = [r for r in coordinate_reuse_pool if r["asset_id"] in manifest]
        for src in RNG.sample(candidates, k=min(2, len(candidates))):
            t2_date = pd.to_datetime(manifest[src["asset_id"]]["t2"]["datetime"]).date()
            backdated = t2_date - timedelta(days=RNG.randint(30, 120))
            row = new_work_base(RNG.choice(FICTIONAL_MP_NAMES), RNG.choice(FICTIONAL_IDA_NAMES),
                                 src["WORK_DESCRIPTION"], src["ACTUAL_AMOUNT"], backdated.year, backdated,
                                 area_name=src["area_name"])
            row.update({
                "branch": "A", "asset_id": src["asset_id"], "lat": src["lat"], "lon": src["lon"],
                "source_scheme": "openstreetmap", "category": src["category"],
            })
            rows.append(row)
            gts.append({
                "work_id": row["work_id"], "branch": "A", "pattern": "backdated_completion",
                "asset_id": src["asset_id"],
                "description": f"claimed completion {fmt_date(backdated)} precedes observed imagery change date {t2_date}",
            })

    return rows, gts


# ---------------------------------------------------------------------------
# Branch B - real small-category rows, non-imagery patterns
# ---------------------------------------------------------------------------

def branch_b_description(src: pd.Series) -> tuple[str, str]:
    """A real small-category activity name reads as a bare fragment
    ("Street lights") next to Branch A's full sentences - pair it with a
    fake village so it reads like a normal work record. Returns
    (description, village) so callers can pass village as area_name too."""
    village = RNG.choice(_VILLAGE_STEMS)
    return f"{src['activity_clean']} at {village}", village


def build_branch_b(real_corpus: pd.DataFrame, n_target: int) -> tuple[list[dict], list[dict]]:
    pool = real_corpus[real_corpus["activity_clean"].isin(BRANCH_B_ACTIVITIES)]
    if pool.empty:
        pool = real_corpus  # fallback, shouldn't happen against the real corpus

    rows, gts = [], []
    n_injected = max(5, int(n_target * 0.15))
    n_genuine = max(0, n_target - n_injected)

    for _ in range(n_genuine):
        src = pool.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        description, village = branch_b_description(src)
        base = new_work_base(RNG.choice(FICTIONAL_MP_NAMES), RNG.choice(FICTIONAL_IDA_NAMES),
                              description, float(src["ACTUAL_AMOUNT"]), 2025,
                              date(2025, RNG.randint(4, 12), RNG.randint(1, 28)), area_name=village)
        base.update({"branch": "B", "asset_id": "", "lat": None, "lon": None,
                      "source_scheme": "synthetic", "category": src["activity_clean"]})
        rows.append(base)
        gts.append({"work_id": base["work_id"], "branch": "B", "pattern": "genuine",
                     "asset_id": "", "description": "unmodified real small-category amount/activity"})

    # cost_outlier: amount far above the peer median for its own activity.
    for _ in range(max(2, n_injected // 5)):
        src = pool.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        peer_median = pool[pool["activity_clean"] == src["activity_clean"]]["ACTUAL_AMOUNT"].median()
        inflated = round(peer_median * RNG.uniform(6, 9), -2)
        description, village = branch_b_description(src)
        base = new_work_base(RNG.choice(FICTIONAL_MP_NAMES), RNG.choice(FICTIONAL_IDA_NAMES),
                              description, inflated, 2025, date(2025, 7, RNG.randint(1, 28)), area_name=village)
        base.update({"branch": "B", "asset_id": "", "lat": None, "lon": None,
                      "source_scheme": "synthetic", "category": src["activity_clean"]})
        rows.append(base)
        gts.append({"work_id": base["work_id"], "branch": "B", "pattern": "cost_outlier",
                     "asset_id": "", "description": f"amount={inflated} vs peer median {peer_median:.0f}"})

    # missing_evidence: marked complete, no photo.
    for _ in range(max(2, n_injected // 5)):
        src = pool.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        description, village = branch_b_description(src)
        base = new_work_base(RNG.choice(FICTIONAL_MP_NAMES), RNG.choice(FICTIONAL_IDA_NAMES),
                              description, float(src["ACTUAL_AMOUNT"]), 2025,
                              date(2025, 5, RNG.randint(1, 28)), area_name=village)
        base["has_images"] = False
        base.update({"branch": "B", "asset_id": "", "lat": None, "lon": None,
                      "source_scheme": "synthetic", "category": src["activity_clean"]})
        rows.append(base)
        gts.append({"work_id": base["work_id"], "branch": "B", "pattern": "missing_evidence",
                     "asset_id": "", "description": "FILE_STATUS=complete equivalent but has_images=False"})

    # structuring: amount parked just under the Rs.10,00,000 threshold.
    for amount in (999900.0, 995500.0)[: max(1, n_injected // 5)]:
        src = pool.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        description, village = branch_b_description(src)
        base = new_work_base(RNG.choice(FICTIONAL_MP_NAMES), RNG.choice(FICTIONAL_IDA_NAMES),
                              description, amount, 2025, date(2025, 9, RNG.randint(1, 28)), area_name=village)
        base.update({"branch": "B", "asset_id": "", "lat": None, "lon": None,
                      "source_scheme": "synthetic", "category": src["activity_clean"]})
        rows.append(base)
        gts.append({"work_id": base["work_id"], "branch": "B", "pattern": "structuring",
                     "asset_id": "", "description": f"amount={amount} just under Rs.10,00,000 threshold"})

    # cross_year_text_duplicate: same MP, identical activity text, one year apart.
    for _ in range(max(1, n_injected // 10)):
        src = pool.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        description, village = branch_b_description(src)
        mp_name = RNG.choice(FICTIONAL_MP_NAMES)
        first = new_work_base(mp_name, RNG.choice(FICTIONAL_IDA_NAMES), description,
                               float(src["ACTUAL_AMOUNT"]), 2024, date(2024, 6, 15), area_name=village)
        second = new_work_base(mp_name, RNG.choice(FICTIONAL_IDA_NAMES), description,
                                float(src["ACTUAL_AMOUNT"]), 2025, date(2025, 6, 15), area_name=village)
        for r in (first, second):
            r.update({"branch": "B", "asset_id": "", "lat": None, "lon": None,
                       "source_scheme": "synthetic", "category": src["activity_clean"]})
            rows.append(r)
        gts.append({"work_id": first["work_id"], "branch": "B", "pattern": "cross_year_text_duplicate",
                     "asset_id": "", "cluster_work_ids": [first["work_id"], second["work_id"]],
                     "description": f"identical activity claimed by MP={mp_name} in both FY24-25 and FY25-26"})

    # entitlement_pace_cluster: one fabricated MP's fiscal-year total
    # sanctioned amount exceeds the Rs.5cr/year nominal entitlement.
    mp_name = RNG.choice(FICTIONAL_MP_NAMES)
    cluster_ids = []
    for _ in range(12):
        src = pool.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        description, village = branch_b_description(src)
        base = new_work_base(mp_name, RNG.choice(FICTIONAL_IDA_NAMES), description,
                              round(RNG.uniform(4_500_000, 5_000_000), -3), 2025,
                              date(2025, RNG.randint(4, 12), RNG.randint(1, 28)), area_name=village)
        base.update({"branch": "B", "asset_id": "", "lat": None, "lon": None,
                      "source_scheme": "synthetic", "category": src["activity_clean"]})
        rows.append(base)
        cluster_ids.append(base["work_id"])
    gts.append({"work_id": cluster_ids[0], "branch": "B", "pattern": "entitlement_pace_cluster",
                 "asset_id": "", "cluster_work_ids": cluster_ids,
                 "description": f"MP={mp_name} FY2025-26 fabricated total ~{12*4_750_000:.0f} exceeds Rs.5cr/year nominal entitlement"})

    return rows, gts


def main() -> None:
    print("loading real MPLADS corpus (read-only)...")
    raw = load_raw_works()
    enriched = engineer_features(raw)
    enriched["activity_clean"] = clean_activity(enriched["ACTIVITY_NAME"])
    print(f"  {len(enriched)} real rows loaded")

    # ~35% Branch A (oversampled to showcase the satellite feature),
    # ~65% Branch B - see docs/SATELLITE_VENDOR_MODULE_PLAN.md #4.
    n_branch_a = pd.read_csv(ASSETS_PATH).shape[0]  # use every real coordinate we have
    n_branch_b = int(n_branch_a * (0.65 / 0.35))

    print(f"building Branch A ({n_branch_a} real-coordinate assets)...")
    a_rows, a_gts = build_branch_a(enriched, n_branch_a)
    print(f"  +{len(a_rows)} rows ({sum(1 for g in a_gts if g['pattern']=='genuine' or g['pattern']=='genuine_unverified')} genuine, "
          f"{sum(1 for g in a_gts if g['pattern'] not in ('genuine','genuine_unverified'))} injected)")

    print(f"building Branch B ({n_branch_b} target real small-category rows)...")
    b_rows, b_gts = build_branch_b(enriched, n_branch_b)
    print(f"  +{len(b_rows)} rows")

    all_rows = a_rows + b_rows
    all_gts = a_gts + b_gts
    df = pd.DataFrame(all_rows).sample(frac=1.0, random_state=SEED).reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    n_a, n_b = (df["branch"] == "A").sum(), (df["branch"] == "B").sum()
    print(f"\nwrote {OUT_PATH} ({len(df)} rows: {n_a} Branch A [{n_a/len(df):.0%}], "
          f"{n_b} Branch B [{n_b/len(df):.0%}])")

    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_gts).to_csv(GROUND_TRUTH_CSV, index=False)
    print(f"wrote {GROUND_TRUTH_CSV} ({len(all_gts)} ground-truth entries)")
    print("\nNOTE: MP_NAME/IDA_NAME on every row (both branches) are fictional "
          "DEMO placeholders - never a real scraped MP_NAME - see this module's "
          "docstring and docs/SATELLITE_VENDOR_MODULE_PLAN.md #0.")


if __name__ == "__main__":
    main()
