# NAZAR
Evidence-led MPLADS review prototype; computational signals always need human review.

## Run (Windows, Python 3.12 and Node.js)
```cmd
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\pipeline.py
.venv\Scripts\python.exe scripts\evaluate.py
npm --prefix frontend install
npm --prefix frontend run build
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```
Open http://127.0.0.1:8000; choose a persona, open a work, inspect evidence, and record a reason.
Use `--root PATH` or `NAZAR_DATA_ROOT` to choose the existing corpus; no scraper is run.
If this copy has no completed CSVs, the pipeline reads `..\sih\mplads_india` and records that source in `reports\pipeline.json`.
Run `.venv\Scripts\python.exe scripts\check_prototype.py` for isolated API/SQLite checks and evidence contact sheets.
The snapshot has 5,611 works / 5 states / 79 constituencies; 266 attachments failed extraction and are logged.
Limits: persona selection is not authentication; district clusters are not official boundaries; amount is a per-unit proxy only.
Thresholds are unsourced heuristics; shared forms can survive pHash gating; no SIFT/ORB, OCR or legal inference; validation is synthetic only. Tailwind CDN and optional Google fonts use network; core CSS is bundled.
See `reports\evaluation.md`, `reports\verification.md` and the preserved earlier ingestion README at `docs\INGESTION_README.md`.
