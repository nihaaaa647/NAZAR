# Satellite module — measured data reality

Companion to `docs/DATA_REALITY.md`, scoped to the satellite/vendor module
(`docs/SATELLITE_VENDOR_MODULE_PLAN.md`). Same rule applies: numbers below
describe what was actually pulled and measured in this environment on
2026-09-25, not a general claim about source coverage or the module's
eventual accuracy. Reproduce coordinate sourcing with
`python -m pipeline.harvest_geotags`, imagery with
`python -m pipeline.fetch_satellite_pairs`, and change-detection with
`python -m ml.cv.satellite_change`.

## Source deviation from the plan

See `docs/DECISIONS.md` (2026-09-25 entry) for the full access-spike
writeup. Short version: Bhuvan NREGA and PMGSY GRRIS/OMMAS (the plan's
named sources) are both gated — Bhuvan behind BDO/DPC portal credentials,
PMGSY behind `.nic.in` domains unreachable from this environment, and
separately its open facility data doesn't cover road-work assets anyway.
Copernicus (the named imagery source) has an open catalog but requires a
free-account OAuth token for every pixel download, which this agent
cannot create on the user's behalf.

Substituted: **OpenStreetMap** (via Overpass API) for coordinates,
**Element84 Earth Search** (STAC API over the public AWS `sentinel-cogs`
bucket) for Sentinel-2 imagery. Both are public, no-account, and verified
reachable with real data returned — confirmed by direct HTTP requests
against Copernicus's own catalog (product IDs, footprints, real 2026
dates over Hyderabad) and by visually inspecting a fetched quicklook
(a recognizable dam shoreline, not a placeholder).

## Coordinate sourcing (§1)

Pulled once, 2026-09-25, cached in `data/geotags/_osm_seed_cache.json`
(live Overpass fetch is the default path in `harvest_geotags.py`; this
cache is the fallback when a mirror is unreachable or overloaded, which
happened repeatedly during this session — see below).

| Category | Count | Region |
|---|---:|---|
| community_centre | 40 | Telangana |
| road | 7 | Telangana |
| dam | 2 | Telangana |
| **Total** | **49** | Telangana only |

This is a **single-state, qualitative sample** (dozens of hand-picked
sites), not corpus-scale — matches the plan's own stated fallback for
when the named sources stall. Bihar and Andhra Pradesh bboxes are wired
into `harvest_geotags.py`'s `BBOXES` list but returned no data this run;
the public Overpass mirrors used (`overpass.kumi.systems`,
`overpass-api.de`) were repeatedly slow, rate-limited, or timed out
across the session, including on a second and third attempt at the
larger multi-state query. This is a live-service reliability issue, not
evidence those regions lack OSM coverage — a re-run when the mirrors are
less loaded should extend coverage without any code change.

A meaningful fraction of the `community_centre` rows are named as
function halls / convention centres / gated-community clubhouses rather
than the rural government-panchayat community halls MPLADS actually
funds (e.g. "YMCA", "Vipasana Meditation Center", "SVM Grand"). They are
still real, real-coordinate OSM features in the right tag category — this
is a category-precision caveat on the *demo's realism*, not a fabrication
concern.

## Imagery retrieval (§2)

Sentinel-2 L2A, ~10m/pixel, red+NIR bands + true-color visual, windowed
128×128px crop (~1.28km²) centered on each coordinate. Two dates per
asset: earliest and latest available scene under 30% cloud cover, per
`fetch_satellite_pairs.py`'s `pick_pair`.

**Resolution caveat, checked against a sample rather than assumed:** at
10m/pixel, a single MPLADS-scale asset (a streetlight, a small bore well,
a small culvert) is far below what Sentinel-2 can resolve — this is
exactly why the module's Branch A/B split exists (§4), not a general
disclaimer. Even within Branch A, a small community hall's roof may only
cover a handful of pixels; only larger-footprint changes (a new road
segment, a filled/expanded check-dam, a new building footprint) are
plausibly visible at all. This has not yet been checked pattern-by-pattern
against the fetched imagery — that check belongs in the evaluation step
(§7), not asserted here.

## Change detection (§3)

Baseline only (NDVI delta + normalized pixel diff on red/NIR), both
signals must exceed their threshold before `change_detected=True` — see
`ml/cv/satellite_change.py` module docstring for the exact thresholds and
why both signals are required together (reduces false positives from
seasonal vegetation swings alone, which move NDVI regardless of any real
construction). The Siamese change-detection stretch goal is not
implemented.

**Measured, 2026-09-25, on the first 10 fetched assets** (2 dams, 8
community centres, all Telangana, t1≈late Apr 2026 / t2≈Aug–Sep 2026):
`change_detected=True` on 0/10. This is the *expected* real-world answer —
none of these are active MPLADS-style construction sites, they're
long-standing existing infrastructure (e.g. Himayath Sagar Dam, built
1927), so a correct detector should find no footprint change on any of
them. Two of the ten (osm_5, osm_8) show `ndvi_t1_mean=0.0` exactly,
which is more likely a windowed-crop artifact (the 128px window landing
partly on a no-data/black tile edge in the t1 scene) than a real ground
condition — flagged here rather than silently accepted, and worth
checking before trusting NDVI values on those two specifically.

**Important limitation this result surfaces, not papered over:** because
every one of these 10 real assets shows no real change, none of them
were labeled `genuine` with a definitive scored result in the
`satellite_fraud_injection.py` ground truth (see `evaluate_satellite_module.py`
output — `genuine_correctly_not_flagged: no genuine works with a scored
change result`). So while the pipeline correctly avoids false-flagging
stable real infrastructure, this specific 10-asset sample has not yet
demonstrated the detector correctly recognizing a *real, in-progress*
change either — that needs either a larger sample that happens to catch
an actively-changing site, or a synthetic before/after pair constructed
specifically to validate the positive case. Not yet done.

## What this module does not claim

Same posture as `docs/SATELLITE_VENDOR_MODULE_PLAN.md` §0: no MPLADS
geotags were used (none are public), no specific MP/IDA/vendor here is
real, and every MP_NAME/IDA_NAME/vendor_id in
`data/canonical/satellite_works.csv` and `vendor_network.csv` is
fictional — including on Branch B rows drawn from real small-category
MPLADS cost data. The coordinates (Branch A) and the cost distributions
(both branches) are real; the paperwork layered on top of them is not.

**Naming style, 2026-09-27 update:** names were originally literal
`DEMO MP 01`/`Sample District Development Authority 1`/`DEMO Vendor 01`
placeholders. Changed to realistic-*styled* fictional names (e.g. "Manoj
Choudhary", "Bhavanipet Zilla Parishad", "Vinayaka Infra Projects Pvt
Ltd") plus a fake village/area name per work and a full MPLADS-style
`WORK_DESCRIPTION` ("Construction of community center and community hall
at Gopalpet" rather than "community_centre: osm_4") — same convention
this project already uses for its own demo persona ("Arvind Dharmapuri"
in `data/personas.json`). Deliberately generic combinations (common first
names × common surnames, generic -puram/-nagar/-pet toponyms, generic
firm-type suffixes) so nothing is styled after one specific real person,
place or company. The demo/fictional disclaimer now lives entirely in
the UI copy and this doc, not in the values themselves — see
`pipeline/satellite_fraud_injection.py` and `ml/anomaly/vendor_network.py`
docstrings for the exact name pools.
