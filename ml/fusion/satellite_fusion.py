"""
Satellite module, step 6 - fusion (see docs/SATELLITE_VENDOR_MODULE_PLAN.md #6).

Scoping note this module must be explicit about: the plan's #6 describes
adding two advisory signals to `scripts/pipeline.py`'s `score_works`
weighted-sum table - i.e. patching the REAL corpus's scorer. That isn't
done here, deliberately. `score_works` scores real WORK_IDs from the real
scraped corpus, none of which have a real coordinate or a real vendor
(no public MPLADS-to-coordinate mapping exists - see the access-spike
writeup in docs/DECISIONS.md). Bolting a fabricated satellite/vendor
signal onto a REAL work's risk_score would misattribute risk to an actual
project. Instead, this module scores the satellite module's OWN synthetic
population (data/canonical/satellite_works.csv, which already carries
branch-appropriate real-or-fabricated signals) using the same weighted-sum
philosophy and the same "advisory, provisional weight, out of the Critical
floor" posture as score_works - applied to data that actually has these
two signals, joined by MP_NAME (proj-nal composite of AC + peer z-score) and
vendor_id. If a real coordinate/vendor mapping is ever built for the real
corpus, this scorer's approach - not scripts/pipeline.py's - would extend
to it.

Signals used here (subset of the real project's 8, reimplemented against
this module's own schema since it's shaped differently from the real
corpus's engineered columns):
  - cost_peer: z-score vs same-category peers within this synthetic set
  - missing_evidence: has_images == False
  - satellite_signal (NEW, provisional weight, Branch A only): derived
    from ml/cv/satellite_change.py's change_detected for phantom_work/
    backdated_completion/coordinate_reuse rows. Branch B rows EXCLUDE this
    term from the sum entirely (not zeroed) - see plan #4/#6's "satellite
    verification not applicable" framing.
  - vendor_network_signal (NEW, provisional weight, both branches):
    ml/anomaly/vendor_network.py's network_risk_score for this row's vendor.

Usage:
    python -m ml.fusion.satellite_fusion
"""

import json
from pathlib import Path

import pandas as pd

WORKS_PATH = Path("data/canonical/satellite_works.csv")
CHANGE_RESULTS_PATH = Path("data/canonical/satellite_change_results.csv")
VENDOR_NETWORK_PATH = Path("data/canonical/vendor_network.csv")
OUT_PATH = Path("data/canonical/satellite_works_scored.csv")

# Provisional weights - deliberately modest and NOT load-bearing until a
# real per-pattern recall number exists (see plan #6). cost_peer/
# missing_evidence mirror the real pipeline's weights (scripts/pipeline.py)
# for the signals this population can also compute. round_amount was
# dropped from the real pipeline (see docs/DECISIONS.md - bare heuristic,
# no statistical/regulatory basis, never validated) and is not reimplemented
# here either.
WEIGHTS = {
    "cost_peer": 15, "missing_evidence": 5,
    "satellite_signal": 15, "vendor_network_signal": 10,
}


def cost_peer_signal(df: pd.DataFrame) -> pd.Series:
    z = pd.Series(0.0, index=df.index)
    for category, group in df.groupby("category"):
        mean, std = group["ACTUAL_AMOUNT"].mean(), group["ACTUAL_AMOUNT"].std()
        if std and std > 0:
            z.loc[group.index] = (group["ACTUAL_AMOUNT"] - mean) / std
    return (z.abs() > 2.5).astype(float)


def satellite_signal(df: pd.DataFrame) -> pd.Series:
    """Branch A only: 1.0 if the asset's real imagery shows no detected
    change (phantom-work-shaped), 0.0 if it shows real change. Branch B
    rows get NaN, meaning "excluded from the sum", not 0 - see module
    docstring."""
    out = pd.Series(float("nan"), index=df.index)
    if not CHANGE_RESULTS_PATH.exists():
        return out
    change = pd.read_csv(CHANGE_RESULTS_PATH).set_index("asset_id")["change_detected"]
    branch_a = df["branch"] == "A"
    for i, row in df[branch_a].iterrows():
        asset_id = row.get("asset_id")
        if asset_id in change.index:
            out.loc[i] = float(not bool(change.loc[asset_id]))
    return out


def vendor_network_signal(df: pd.DataFrame) -> pd.Series:
    out = pd.Series(0.0, index=df.index)
    if not VENDOR_NETWORK_PATH.exists() or "vendor_id" not in df.columns:
        return out
    vendor_scores = pd.read_csv(VENDOR_NETWORK_PATH).set_index("vendor_id")["network_risk_score"]
    for i, row in df.iterrows():
        vid = row.get("vendor_id")
        if pd.notna(vid) and vid in vendor_scores.index:
            out.loc[i] = float(vendor_scores.loc[vid])
    return out


def main() -> None:
    df = pd.read_csv(WORKS_PATH)
    signals = pd.DataFrame({
        "cost_peer": cost_peer_signal(df),
        "missing_evidence": (~df["has_images"].astype(bool)).astype(float),
        "satellite_signal": satellite_signal(df),
        "vendor_network_signal": vendor_network_signal(df),
    })

    risk_scores, bands, signals_json = [], [], []
    for i in df.index:
        row_signals = signals.loc[i]
        # satellite_signal is NaN (excluded, not zeroed) for Branch B and
        # for Branch A rows with no scored imagery yet.
        applicable = {k: v for k, v in row_signals.items() if pd.notna(v)}
        weighted_sum = sum(WEIGHTS[k] * v for k, v in applicable.items())
        max_possible = sum(WEIGHTS[k] for k in applicable)
        risk = round(100 * weighted_sum / max_possible, 2) if max_possible else 0.0
        band = "Critical" if risk > 80 else "High" if risk > 60 else "Moderate" if risk > 30 else "Low"
        risk_scores.append(risk)
        bands.append(band)
        signals_json.append(json.dumps({k: (None if pd.isna(v) else round(float(v), 3))
                                          for k, v in row_signals.items()}))

    df["risk_score"] = risk_scores
    df["severity_band"] = bands
    df["signals_json"] = signals_json
    df["review_notice"] = "Computational signal — needs human review."

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"wrote {OUT_PATH} ({len(df)} rows)")
    print(df.groupby("branch")["severity_band"].value_counts().to_string())


if __name__ == "__main__":
    main()
