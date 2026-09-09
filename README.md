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
Open http://127.0.0.1:8000; sign in, filter the queue (severity, status, or "Any review signal" to see only works flagged for one reason), open a work, inspect evidence, and record a reason.
Use `--root PATH` or `NAZAR_DATA_ROOT` to choose the existing corpus; no scraper is run.

Sign-in is a makeshift demo gate: one fixed account per persona, verified server-side, which
issues an HMAC-signed session token (`Authorization: Bearer`, 8 h) that carries the role and
jurisdiction — there is no role picker. Demo accounts (user ID / password):
`mp.office` / `mp-lookcloser-24`, `district.authority` / `district-lookcloser-24`,
`state.nodal` / `state-lookcloser-24`, `ministry` / `ministry-lookcloser-24`. Override with
`NAZAR_USERS="persona_id:user:pass,..."` and set `NAZAR_AUTH_SECRET` for anything shared.
If this copy has no completed CSVs, the pipeline reads `..\sih\mplads_india` and records that source in `reports\pipeline.json`.
Run `.venv\Scripts\python.exe scripts\check_prototype.py` for isolated API/SQLite checks and evidence contact sheets.
The snapshot has 5,611 works / 5 states / 79 constituencies; 266 attachments failed extraction and are logged.
Limits: sign-in is a fixed-account demo gate, not real identity management (no signup, reset, or per-user accounts); district clusters are not official boundaries; amount is a per-unit proxy only.
Thresholds are unsourced heuristics; shared forms can survive pHash gating; no SIFT/ORB, OCR or legal inference; validation is synthetic only. Tailwind CDN and optional Google fonts use network; core CSS is bundled.
See `reports\evaluation.md`, `reports\verification.md` and the preserved earlier ingestion README at `docs\INGESTION_README.md`.
