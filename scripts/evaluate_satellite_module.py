"""
Satellite module, step 7 - evaluation (see
docs/SATELLITE_VENDOR_MODULE_PLAN.md #7).

Reports recall SEPARATELY per branch, not pooled - a pooled number could
hide one branch underperforming behind the other, and per-branch numbers
are what proves this module isn't cherry-picking a favorable subset (see
plan #7 and #4's sampling-ratio note). This is a companion to, not a
replacement for, scripts/evaluate.py's existing photo/text/cost pattern
recall reporting.

"Recall" here means: of the injected fraud rows planted by
pipeline/satellite_fraud_injection.py, how many would the relevant
detector flag. Branch A's detector is ml/cv/satellite_change.py's
change_detected result (a phantom_work row should show
change_detected=False; a genuine row should show change_detected=True).
Branch B's detectors are the same rule-shaped checks already used
elsewhere in this project (cost z-score, missing evidence, sub-10L
structuring, exact-text duplication, entitlement pace) - reimplemented
here directly against satellite_works.csv rather than imported, since
scripts/pipeline.py's score_works works against the real corpus's raw
schema, not this module's fabricated-but-differently-shaped rows (see
plan #6 - full fusion integration is a separate, not-yet-done step).

Usage:
    python -m scripts.evaluate_satellite_module
"""

from pathlib import Path

import pandas as pd

WORKS_PATH = Path("data/canonical/satellite_works.csv")
GROUND_TRUTH_PATH = Path("eval/satellite_ground_truth.csv")
CHANGE_RESULTS_PATH = Path("data/canonical/satellite_change_results.csv")

STRUCTURING_MAX = 1_000_000
COST_OUTLIER_Z = 2.5


def evaluate_branch_a(works: pd.DataFrame, gt: pd.DataFrame) -> dict:
    if not CHANGE_RESULTS_PATH.exists():
        return {"error": f"{CHANGE_RESULTS_PATH} not found - run ml.cv.satellite_change first"}
    change = pd.read_csv(CHANGE_RESULTS_PATH).set_index("asset_id")["change_detected"]

    gt_a = gt[gt["branch"] == "A"]
    results = {}
    for pattern in ("phantom_work", "coordinate_reuse", "backdated_completion"):
        rows = gt_a[gt_a["pattern"] == pattern]
        if rows.empty:
            results[pattern] = "no injected instances this run"
            continue
        # detector signal: change_detected should be False for a phantom/fabricated claim
        hits = sum(
            1 for asset_id in rows["asset_id"]
            if asset_id in change.index and not bool(change.loc[asset_id])
        )
        results[pattern] = f"{hits}/{len(rows)} flagged (change_detected=False)"

    genuine_ids = gt_a[gt_a["pattern"].isin(["genuine", "genuine_unverified"])]["asset_id"]
    genuine_correct = sum(
        1 for asset_id in genuine_ids
        if asset_id in change.index and bool(change.loc[asset_id])
    )
    n_genuine_checked = sum(1 for asset_id in genuine_ids if asset_id in change.index)
    results["genuine_correctly_not_flagged"] = (
        f"{genuine_correct}/{n_genuine_checked} genuine works correctly show change_detected=True"
        if n_genuine_checked else "no genuine works with a scored change result"
    )
    return results


def evaluate_branch_b(works: pd.DataFrame, gt: pd.DataFrame) -> dict:
    gt_b = gt[gt["branch"] == "B"]
    works_b = works[works["branch"] == "B"].set_index("work_id")
    results = {}

    def flagged_ids(pattern_name: str) -> set:
        rows = gt_b[gt_b["pattern"] == pattern_name]
        ids = set()
        for _, r in rows.iterrows():
            cluster = r.get("cluster_work_ids")
            if isinstance(cluster, str) and cluster.startswith("["):
                ids.update(int(x) for x in cluster.strip("[]").replace("'", "").split(", ") if x)
            else:
                ids.add(int(r["work_id"]))
        return ids

    structuring_ids = flagged_ids("structuring")
    hits = sum(1 for wid in structuring_ids if wid in works_b.index and
               works_b.loc[wid, "ACTUAL_AMOUNT"] < STRUCTURING_MAX)
    results["structuring"] = f"{hits}/{len(structuring_ids)} flagged (amount < Rs.10,00,000)" if structuring_ids else "none injected"

    missing_ids = flagged_ids("missing_evidence")
    hits = sum(1 for wid in missing_ids if wid in works_b.index and not works_b.loc[wid, "has_images"])
    results["missing_evidence"] = f"{hits}/{len(missing_ids)} flagged (has_images=False)" if missing_ids else "none injected"

    cost_ids = flagged_ids("cost_outlier")
    hits = 0
    for wid in cost_ids:
        if wid not in works_b.index:
            continue
        row = works_b.loc[wid]
        peers = works_b[works_b["category"] == row["category"]]["ACTUAL_AMOUNT"]
        if len(peers) > 1 and peers.std() > 0:
            z = (row["ACTUAL_AMOUNT"] - peers.mean()) / peers.std()
            hits += int(z > COST_OUTLIER_Z)
    results["cost_outlier"] = f"{hits}/{len(cost_ids)} flagged (z > {COST_OUTLIER_Z})" if cost_ids else "none injected"

    dup_ids = flagged_ids("cross_year_text_duplicate")
    hits = 0
    for wid in dup_ids:
        if wid not in works_b.index:
            continue
        row = works_b.loc[wid]
        dupes = works_b[(works_b["WORK_DESCRIPTION"] == row["WORK_DESCRIPTION"]) &
                         (works_b["MP_NAME"] == row["MP_NAME"])]
        hits += int(len(dupes) > 1)
    results["cross_year_text_duplicate"] = f"{hits}/{len(dup_ids)} flagged (duplicate MP+description pair found)" if dup_ids else "none injected"

    ent_ids = flagged_ids("entitlement_pace_cluster")
    if ent_ids:
        mp_totals = works_b.groupby("MP_NAME")["ACTUAL_AMOUNT"].sum()
        flagged_mps = set(mp_totals[mp_totals > 50_000_000].index)
        cluster_mps = {works_b.loc[wid, "MP_NAME"] for wid in ent_ids if wid in works_b.index}
        results["entitlement_pace_cluster"] = f"{len(cluster_mps & flagged_mps)}/{len(cluster_mps)} MPs flagged (FY total > Rs.5cr)"
    else:
        results["entitlement_pace_cluster"] = "none injected"

    return results


def main() -> None:
    if not WORKS_PATH.exists() or not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(
            "run `python -m pipeline.satellite_fraud_injection` first to produce "
            f"{WORKS_PATH} and {GROUND_TRUTH_PATH}"
        )
    works = pd.read_csv(WORKS_PATH)
    gt = pd.read_csv(GROUND_TRUTH_PATH)

    print("=== Branch A (satellite-visible, imagery-based patterns) ===")
    for pattern, result in evaluate_branch_a(works, gt).items():
        print(f"  {pattern}: {result}")

    print("\n=== Branch B (non-visible, existing rule-shaped patterns) ===")
    for pattern, result in evaluate_branch_b(works, gt).items():
        print(f"  {pattern}: {result}")


if __name__ == "__main__":
    main()
