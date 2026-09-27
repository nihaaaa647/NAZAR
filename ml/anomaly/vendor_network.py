"""
Satellite module, step 5 - vendor/payment network signal (see
docs/SATELLITE_VENDOR_MODULE_PLAN.md #5).

Real financial/vendor data isn't public (same reason this whole track is
synthetic - see plan #0), so this is fabricated by necessity, same as
the rest of this module's overlay. Builds a vendor pool, assigns every
work in data/canonical/satellite_works.csv a vendor, and injects five
patterns, each independently identifiable in the ground truth:

  - vendor_concentration: one vendor wins a disproportionate share of one
    MP's works.
  - shell_vendor_signature: vendor's registration date falls in the
    30 days immediately before its first win.
  - bid_collusion: near-identical amounts awarded to nominally different
    vendors for the same activity/MP/time window (this project's data
    model tracks awarded works, not competing bids, so collusion is
    modeled as suspiciously-close awarded amounts across vendors rather
    than literal rival bid sheets).
  - split_invoicing: same vendor+MP, multiple amounts just under the
    existing Rs.10L structuring threshold within a short window - reuses
    the structuring threshold already used in pipeline/fraud_injection.py
    and pipeline/satellite_fraud_injection.py rather than inventing a new
    one.
  - round_tripping: a vendor's award is followed within days by a
    similar-sized award to a second, shell-flagged vendor - modeled via
    a lightweight fabricated payment ledger (vendor_id, work_id, amount,
    payment_date), not a real transaction trace.

Scope: BOTH branches (see plan #5's explicit note) - a fraud ring
plausibly spans satellite-visible and non-visible work types for the
same MP/IDA, so the graph isn't restricted to Branch A.

Graph: vendor<->MP<->IDA<->asset, built with networkx. Vendor
network_risk_score = a weighted combination of (a) this vendor's share
of pattern-flagged works it's involved in, and (b) its degree centrality
in the bipartite vendor-MP graph (a vendor spread thin across many MPs
reads differently than one concentrated on a single MP - centrality
alone doesn't distinguish these, so it's combined with the pattern flags
rather than used alone).

Output: data/canonical/vendor_network.csv -
  {vendor_id, registration_date, n_works, mp_names, ida_names,
   total_amount, contributing_patterns, network_risk_score}
and eval/vendor_network_ground_truth.csv (which (vendor_id, pattern)
pairs were deliberately injected).

Usage:
    python -m ml.anomaly.vendor_network
"""

import random
from datetime import date, timedelta
from pathlib import Path

import networkx as nx
import pandas as pd

WORKS_PATH = Path("data/canonical/satellite_works.csv")
OUT_PATH = Path("data/canonical/vendor_network.csv")
GROUND_TRUTH_PATH = Path("eval/vendor_network_ground_truth.csv")

SEED = 20260925
RNG = random.Random(SEED)

N_VENDORS = 18
STRUCTURING_MAX = 1_000_000
N_SHELL_VENDORS = 2
N_CONCENTRATED_VENDORS = 2
N_COLLUSION_CLUSTERS = 2
N_SPLIT_INVOICING_VENDORS = 2
N_ROUND_TRIP_PAIRS = 2


# Realistic-*styled* fictional contractor names, not literal "DEMO Vendor N"
# strings - same reasoning as pipeline/satellite_fraud_injection.py's MP/IDA
# names: a name that visibly reads as a placeholder is easy to skim past.
# Generic stems x generic firm-type suffixes, so nothing here is styled
# after one specific real company.
_VENDOR_STEMS = ["Sri Balaji", "Venkateswara", "Om Sai", "Sri Lakshmi", "Krishna",
                 "Sai Ram", "Vinayaka", "Sri Ganesh", "Bhavani", "Rama",
                 "Sri Durga", "Anjaneya", "New Age", "United", "National",
                 "Southern", "Metro", "Deccan"]
_VENDOR_SUFFIXES = ["Constructions", "Infra Projects Pvt Ltd", "Builders", "Enterprises", "& Co"]


def make_vendor_pool() -> pd.DataFrame:
    vendors = []
    names = [f"{s} {_VENDOR_SUFFIXES[i % len(_VENDOR_SUFFIXES)]}" for i, s in enumerate(_VENDOR_STEMS)]
    for i in range(1, N_VENDORS + 1):
        reg_date = date(2015, 1, 1) + timedelta(days=RNG.randint(0, 365 * 9))
        vendors.append({"vendor_id": names[i - 1], "registration_date": reg_date, "is_shell_flagged": False})
    return pd.DataFrame(vendors)


def assign_vendors(works: pd.DataFrame, vendors: pd.DataFrame) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    """Mostly-random vendor assignment, with deliberate pattern injection
    on top - see module docstring for each pattern's construction."""
    works = works.copy()
    works["vendor_id"] = [RNG.choice(vendors["vendor_id"]) for _ in range(len(works))]
    works["award_date"] = pd.to_datetime(works["ACTUAL_END_DATE"], format="%d-%b-%Y", errors="coerce")

    gts = []
    payments = []

    # vendor_concentration: force one vendor to win most of one MP's works.
    mp_pool = works["MP_NAME"].unique()
    for _ in range(N_CONCENTRATED_VENDORS):
        target_mp = RNG.choice(list(mp_pool))
        target_vendor = RNG.choice(vendors["vendor_id"].tolist())
        mp_rows = works[works["MP_NAME"] == target_mp].index
        forced = RNG.sample(list(mp_rows), k=max(1, int(len(mp_rows) * 0.7)))
        works.loc[forced, "vendor_id"] = target_vendor
        gts.append({"vendor_id": target_vendor, "pattern": "vendor_concentration",
                     "description": f"{target_vendor} won {len(forced)}/{len(mp_rows)} of MP={target_mp}'s works"})

    # shell_vendor_signature: registration date immediately before first win.
    shell_vendor_ids = RNG.sample(vendors["vendor_id"].tolist(), k=N_SHELL_VENDORS)
    for vid in shell_vendor_ids:
        vendor_rows = works[works["vendor_id"] == vid]
        if vendor_rows.empty:
            continue
        first_win = vendor_rows["award_date"].min()
        if pd.isna(first_win):
            continue
        new_reg = (first_win - timedelta(days=RNG.randint(3, 25))).date()
        vendors.loc[vendors["vendor_id"] == vid, "registration_date"] = new_reg
        vendors.loc[vendors["vendor_id"] == vid, "is_shell_flagged"] = True
        gts.append({"vendor_id": vid, "pattern": "shell_vendor_signature",
                     "description": f"registered {new_reg}, {(first_win.date()-new_reg).days} days before first win {first_win.date()}"})

    # bid_collusion: 2-4 different vendors awarded near-identical amounts
    # for the same activity/MP/short window.
    for _ in range(N_COLLUSION_CLUSTERS):
        base_row = works.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        cluster_vendors = RNG.sample(vendors["vendor_id"].tolist(), k=3)
        base_amount = base_row["ACTUAL_AMOUNT"]
        cluster_idx = works.sample(min(3, len(works)), random_state=RNG.randint(0, 2**31)).index
        for idx, vid in zip(cluster_idx, cluster_vendors):
            works.loc[idx, "vendor_id"] = vid
            works.loc[idx, "ACTUAL_AMOUNT"] = round(base_amount * RNG.uniform(0.98, 1.02), -2)
            works.loc[idx, "MP_NAME"] = base_row["MP_NAME"]
            works.loc[idx, "award_date"] = base_row["award_date"]
        gts.append({"vendor_id": ";".join(cluster_vendors), "pattern": "bid_collusion",
                     "description": f"amounts within 2% of {base_amount:.0f} for MP={base_row['MP_NAME']}, "
                                     f"same award date, {len(cluster_vendors)} nominally independent vendors"})

    # split_invoicing: same vendor+MP, several amounts just under the
    # structuring threshold within a short window.
    split_vendor_ids = RNG.sample(vendors["vendor_id"].tolist(), k=N_SPLIT_INVOICING_VENDORS)
    for vid in split_vendor_ids:
        target_mp = RNG.choice(list(mp_pool))
        idx = works.sample(min(3, len(works)), random_state=RNG.randint(0, 2**31)).index
        base_date = date(2025, RNG.randint(4, 10), RNG.randint(1, 20))
        for i, ix in enumerate(idx):
            works.loc[ix, "vendor_id"] = vid
            works.loc[ix, "MP_NAME"] = target_mp
            works.loc[ix, "ACTUAL_AMOUNT"] = round(RNG.uniform(950000, 999000), -2)
            works.loc[ix, "award_date"] = pd.Timestamp(base_date + timedelta(days=i * 3))
        gts.append({"vendor_id": vid, "pattern": "split_invoicing",
                     "description": f"{len(idx)} awards to {vid} from MP={target_mp}, each <Rs.10L, within {3*len(idx)} days"})

    # round_tripping: a normal vendor's award is followed within days by a
    # similar-sized payment to a shell-flagged vendor.
    for _ in range(N_ROUND_TRIP_PAIRS):
        src_row = works.sample(1, random_state=RNG.randint(0, 2**31)).iloc[0]
        shell_vid = RNG.choice(shell_vendor_ids) if shell_vendor_ids else vendors["vendor_id"].iloc[0]
        pay_date = src_row["award_date"] if pd.notna(src_row["award_date"]) else pd.Timestamp(date(2025, 6, 1))
        payments.append({"vendor_id": src_row["vendor_id"], "work_id": src_row["work_id"],
                          "amount": src_row["ACTUAL_AMOUNT"], "payment_date": pay_date.date()})
        round_trip_amount = round(src_row["ACTUAL_AMOUNT"] * RNG.uniform(0.9, 0.98), -2)
        round_trip_date = pay_date.date() + timedelta(days=RNG.randint(2, 10))
        payments.append({"vendor_id": shell_vid, "work_id": src_row["work_id"],
                          "amount": round_trip_amount, "payment_date": round_trip_date})
        gts.append({"vendor_id": f"{src_row['vendor_id']};{shell_vid}", "pattern": "round_tripping",
                     "description": f"{src_row['vendor_id']} paid {src_row['ACTUAL_AMOUNT']:.0f} on {pay_date.date()}, "
                                     f"{shell_vid} received {round_trip_amount:.0f} {round_trip_date}"})

    for _, row in works.iterrows():
        payments.append({"vendor_id": row["vendor_id"], "work_id": row["work_id"],
                          "amount": row["ACTUAL_AMOUNT"],
                          "payment_date": row["award_date"].date() if pd.notna(row["award_date"]) else None})

    return works, gts, pd.DataFrame(payments)


def build_graph(works: pd.DataFrame) -> nx.Graph:
    g = nx.Graph()
    for _, row in works.iterrows():
        g.add_node(("vendor", row["vendor_id"]), kind="vendor")
        g.add_node(("mp", row["MP_NAME"]), kind="mp")
        g.add_node(("ida", row["IDA_NAME"]), kind="ida")
        g.add_edge(("vendor", row["vendor_id"]), ("mp", row["MP_NAME"]))
        g.add_edge(("vendor", row["vendor_id"]), ("ida", row["IDA_NAME"]))
        if row.get("asset_id"):
            g.add_node(("asset", row["asset_id"]), kind="asset")
            g.add_edge(("vendor", row["vendor_id"]), ("asset", row["asset_id"]))
    return g


def score_vendors(works: pd.DataFrame, vendors: pd.DataFrame, gts: list[dict], graph: nx.Graph) -> pd.DataFrame:
    centrality = nx.degree_centrality(graph)
    pattern_by_vendor: dict[str, set] = {}
    for g in gts:
        for vid in str(g["vendor_id"]).split(";"):
            pattern_by_vendor.setdefault(vid, set()).add(g["pattern"])

    rows = []
    for _, v in vendors.iterrows():
        vid = v["vendor_id"]
        vworks = works[works["vendor_id"] == vid]
        if vworks.empty:
            continue
        patterns = pattern_by_vendor.get(vid, set())
        vcentrality = centrality.get(("vendor", vid), 0.0)
        # patterns dominate the score (they're the actual injected signal);
        # centrality is a small tiebreaker/context addition, not the driver.
        pattern_score = min(1.0, 0.3 * len(patterns))
        network_risk_score = round(min(1.0, pattern_score + 0.2 * vcentrality), 3)
        rows.append({
            "vendor_id": vid, "registration_date": v["registration_date"],
            "is_shell_flagged": v["is_shell_flagged"], "n_works": len(vworks),
            "mp_names": ";".join(sorted(vworks["MP_NAME"].unique())),
            "ida_names": ";".join(sorted(vworks["IDA_NAME"].unique())),
            "total_amount": round(float(vworks["ACTUAL_AMOUNT"].sum()), 2),
            "contributing_patterns": ";".join(sorted(patterns)),
            "contributing_work_ids": ";".join(str(x) for x in vworks["work_id"]),
            "degree_centrality": round(vcentrality, 4),
            "network_risk_score": network_risk_score,
        })
    return pd.DataFrame(rows).sort_values("network_risk_score", ascending=False)


def main() -> None:
    works = pd.read_csv(WORKS_PATH)
    vendors = make_vendor_pool()
    works, gts, payments = assign_vendors(works, vendors)
    graph = build_graph(works)
    vendor_df = score_vendors(works, vendors, gts, graph)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    vendor_df.to_csv(OUT_PATH, index=False)
    print(f"wrote {OUT_PATH} ({len(vendor_df)} vendors)")
    print(f"  flagged (network_risk_score > 0.3): {(vendor_df['network_risk_score'] > 0.3).sum()}")

    GROUND_TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(gts).to_csv(GROUND_TRUTH_PATH, index=False)
    print(f"wrote {GROUND_TRUTH_PATH} ({len(gts)} injected patterns)")

    # persist vendor_id back onto satellite_works.csv so downstream fusion
    # (ml/fusion/satellite_fusion.py) can join on it.
    works.to_csv(WORKS_PATH, index=False)
    print(f"updated {WORKS_PATH} with vendor_id/award_date columns")


if __name__ == "__main__":
    main()
