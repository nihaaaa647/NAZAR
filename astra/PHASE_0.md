# PHASE 0 — Foundation and Data Reality

Master prompt: `astra/00_MASTER_PROMPT.md`. Read it first if you have not.

## OBJECTIVE

Establish version control, project scaffolding, a reproducible environment, and — the real
point of this phase — an independently measured account of what the data actually is.
No detector logic. No models. Nothing is built on an unverified assumption.

## CONTEXT

The repository currently holds working scrapers (`mplads_common.py`,
`mplads_india_downloader.py`, `backfill_sanctioned.py`, `mplads_telangana.py`,
`reset_sanctioned_progress.py`), one feature-engineering module
(`pipeline/consolidate.py`), the frozen spec (`MPLADS_Implementation_Blueprint.docx`),
`feature_plan.md`, `problem_statement.txt`, a prior review's measurements
(`astra/FINDINGS_TO_VERIFY.md`), and ~5,100 scraped work records with ~3,900 attachments.
There is no git repository and no dependency manifest.

## TASKS

1. `git init`; add a `.gitignore` that excludes `mplads_india/`, `mplads_images/`,
   `__pycache__/`, `.env`, model artefacts and extracted-image caches. Commit the current
   tree as the baseline before changing anything.
2. Read every Python file, `feature_plan.md`, `problem_statement.txt`, and the blueprint in
   full. Extract the blueprint text yourself (it is a .docx; unzip `word/document.xml`) and
   keep a plain-text copy at `docs/blueprint.md` for reference.
3. Create the folder structure from blueprint Part G, adapted to this repository's existing
   layout. Do not move or rename the existing scrapers.
4. Pin the environment: `requirements.txt` (or `pyproject.toml`), `.env.example`, and a
   README section on setup. Record installed vs missing packages; do not install anything
   outside the blueprint stack without asking.
5. **Write `scripts/profile_data.py`** — a re-runnable profiler that emits, for the current
   corpus: row and file counts; per-column null rate, cardinality and top values;
   `WORK_CATEGORY` and derived `activity_norm` distributions; `ACTUAL_AMOUNT` distribution
   including round-number and near-threshold clustering; date ranges and parse-failure rates
   for every date column; `LETTER_NO` parse-failure rate; the completed↔sanctioned join rate
   on `WORK_RECOMMENDATION_DTL_ID`; `SANCTION_AMOUNT` vs `ACTUAL_AMOUNT` differences;
   `WORK_STAGE` distribution; and the attachment inventory by extension, by embedded-image
   presence, by pixel dimensions, and by colourfulness.
6. Run it. **Look at the output.** Then write `docs/DATA_REALITY.md`: your measured numbers,
   which of F1-F8 in `astra/FINDINGS_TO_VERIFY.md` you confirmed, which you corrected, and
   the implications for the design. Include the commands that reproduce each number.
7. Write `docs/STATE.md` and `docs/DECISIONS.md` in the shapes the master prompt requires,
   seeded with this phase.
8. Set up `pytest` with one real test (the `LETTER_NO` parser against known-good and known-
   malformed inputs, including the whitespace-corrupted form `LN/\t MP319/2024-2025/32`).
9. Stop and put ASK #1 (data scope) and ASK #4 (Postgres vs SQLite) to the operator, with
   your recommendations and your default if unanswered.

## CONSTRAINTS

- Do not modify the scrapers' request behaviour in any way.
- Do not delete `pipeline/consolidate.py` or the stale parquet; the parquet is evidence of
  how the schema drifted.
- Do not begin detector or schema work in this phase.

## VALIDATION

`python scripts/profile_data.py` runs to completion over the full corpus and its output is
pasted into your report. `pytest` passes. `git log` shows a baseline commit plus this
phase's work.

## COMPLETION CRITERIA

- `docs/DATA_REALITY.md` exists, is derived from measurements you ran, and explicitly
  confirms or corrects each of F1-F8.
- The environment is reproducible from the manifest on a clean machine.
- The two operator questions are asked.
- Repository is committed and runnable.

## INSPECT BEFORE MOVING ON

Re-read `docs/DATA_REALITY.md` against blueprint Parts B and D. List, in `docs/STATE.md`,
every place the blueprint's schema or engine specification is contradicted by what you
measured. Phase 1 depends on that list being complete.
