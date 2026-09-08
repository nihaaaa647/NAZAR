# NAZAR

Explainable MPLADS work-review platform under development for SIH 26102.
Implementation has started with the Phase 0 data audit. Detectors, database,
API, role-specific dashboard and deployment are not implemented yet.
Computational signals require human verification; they are not findings about misconduct.

## Setup and run

Use Python 3.12 (tested with 3.12.14) from the repository root. Windows PowerShell:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe scripts/profile_data.py
./.venv/Scripts/python.exe -m pytest -q
```

If `python` is not on PATH, invoke your installed Python executable by its full path
for the first command. On macOS/Linux use `.venv/bin/python` instead.
The manifest pins the Phase 0 environment, including transitive dependencies;
later-phase ML/backend packages are intentionally not installed yet.

The corpus is excluded from Git. Supply the existing `mplads_india/` directory
with constituency CSVs and their attachment files, or pass
`--root PATH_TO_CORPUS`. The profiler fails explicitly if there are no completed rows.
It reads the corpus without altering CSVs, attachments, progress or the historical parquet.
It makes no portal requests. `.env.example` lists the optional `NAZAR_DATA_ROOT`
environment variable; export it in your shell or use `--root`.

Outputs are `reports/data_profile.json` (all measurements),
`reports/profile_summary.txt` (console summary) and `reports/attachments.csv`
(per-image measurements and failure paths, regenerated locally).
Use `--output ANOTHER_DIRECTORY` to preserve an earlier report.

## Current layout

- `pipeline/consolidate.py`: existing feature foundation; the profiler exercises it in memory.
- `scripts/profile_data.py`: CSV, join and attachment audit.
- `tests/`: parsers, fiscal-year boundaries, image probing and inventory isolation.
- `docs/blueprint.md`: extracted reference specification.
- `docs/DATA_REALITY.md`, `docs/DECISIONS.md`, `docs/STATE.md`: evidence, choices and next work.
- `backend/`, `frontend/`, `ml/`, `pipelines/`, `docker/`: reserved blueprint folders; no runtime implementation yet.

Keep existing scrapers in place. The maintained downloader is
`mplads_india_downloader.py`, using `mplads_common.py` with its existing delay and retries.
Downloading more data is a separate scope decision; do not run multiple scrapers concurrently.
Older numbered downloaders are historical implementations.

The legacy `pipeline/fraud_injection.py` is **not an approved pipeline entry point**:
it writes synthetic attachments inside raw-data folders, lacks the required explicit
synthetic flag, and uses assumptions superseded by the phase documents. Its existing
outputs are preserved as evidence. Phase 2 must replace this with isolated evaluation
storage before it is used. The profiler only analyzes attachments referenced by raw
completed CSV rows and separately reports all unreferenced files.

The standalone `python -m pipeline.consolidate` command still exists, but overwrites
the historical parquet and retains legacy category/proxy semantics. Use the read-only
profiler for Phase 0; canonical corrections belong to Phase 1.

## Verification limits

This is a foundation increment, not a runnable investigator demo. No measured detector
recall, risk ranking, legal compliance result, OCR prevalence or authentication claim
is available yet. See `docs/STATE.md` for the exact validation performed.
