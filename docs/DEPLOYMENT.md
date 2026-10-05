# NAZAR — Deployment

_As of 2026-09-28 (Phase 5 section F). This file states exactly what is
configured in the repository versus what remains blocked on real
credentials/accounts this development environment does not have — per the
Phase 5 mandatory safeguard: "If deployment credentials or services are
unavailable, report the exact blocker instead of fabricating success."_

## Status: not deployed from this environment

**No live frontend URL, backend URL, or hosted database exists as a result
of this session's work.** This environment has no Vercel account, no
Render account, and no Neon (or other Postgres) account/connection string
— actually creating and deploying to those services requires a human with
account access to run the steps below (or connect this repo to an existing
account). Everything below is the *configuration* that makes that step
possible, verified to be internally consistent, not evidence that a
deployment has happened.

## What IS configured and verified in this repo

### Backend (Render)

`render.yaml`:
```yaml
services:
  - type: web
    name: nazar-api
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: PYTHON_VERSION
        value: 3.12.6
      - key: NAZAR_DATA_DIR
        value: deploy_data
      - key: NAZAR_DATABASE_URL
        sync: false          # prompted at setup time, never committed
      - key: NAZAR_AUTH_SECRET
        generateValue: true
      - key: NAZAR_CORS_ORIGINS
        value: "*"            # MUST be tightened before NAZAR_ENV=production - see below
```
- `requirements.txt` installs cleanly from prebuilt wheels (verified: no
  system-level GDAL/Tesseract/build tools needed — `opencv-python-headless`,
  `rasterio`, `pymupdf`, `psycopg[binary]` all ship wheels for Linux, the
  Render runtime).
- `GET /health`, `GET /ready`, `GET /version`, `GET /capabilities` exist and
  are exercised by `tests/test_production_security.py` (Phase 5 section F).
- **Blocker before this can safely run with `NAZAR_ENV=production`:**
  `NAZAR_CORS_ORIGINS` must be changed from `"*"` to the real Vercel origin
  once that URL exists — the backend now (Phase 5 section E) refuses to
  start in production with a wildcard CORS origin. This is a real,
  intentional gate, not an oversight; render.yaml's `"*"` is a pre-launch
  placeholder, documented here so it isn't missed.
- **Database:** `NAZAR_DATABASE_URL` is `sync: false` (Render prompts for
  it, never stored in the repo). Unset, the backend falls back to a local
  SQLite file — fine for a demo process, but Render's free plan has no
  persistent disk, so reviewer decisions would reset on every cold start
  without a real Postgres (e.g. Neon) connection string supplied here.

### Frontend (Vercel)

- `frontend/src/App.tsx` reads `VITE_API_BASE` at build time
  (`import.meta.env.VITE_API_BASE`) and calls `apiUrl(path)` everywhere
  instead of a hardcoded origin — verified by reading the source, not
  assumed.
- No `vercel.json` exists yet in this repo (Vercel's zero-config Vite
  detection is sufficient for a static Vite build — `npm run build` →
  `frontend/dist` — but nothing here has been deployed to confirm that in
  practice).
- **Blocker:** no Vercel account/project connected from this environment.

### Evidence-file deployment (`deploy_data/`)

- `scripts/prepare_deploy_data.py` builds a trimmed snapshot at
  `deploy_data/` for the free-tier host (Render's free plan has no
  persistent disk large enough for the full local pipeline output).
- **Not independently re-verified in this phase** which images were
  selected/excluded or the exact resulting size — see
  `docs/KNOWN_LIMITATIONS.md` and that script's own docstring for the
  selection method as written.

## Operational endpoints (implemented this phase)

| Endpoint | Purpose |
|---|---|
| `GET /health` | process alive |
| `GET /ready` | database reachable + core data loaded (503 if not) |
| `GET /version` | detector/schema/threshold versions actually embedded in the loaded data, `database: postgres\|sqlite`, build commit if the host sets `RENDER_GIT_COMMIT`/`NAZAR_BUILD_COMMIT` |
| `GET /capabilities` | machine-readable `docs/CAPABILITY_MATRIX.md` |

None require auth and none leak secrets or filesystem paths — verified by
`tests/test_production_security.py::test_health_ready_version_capabilities_endpoints`.

## What a human with account access needs to do to actually deploy

1. Create a Neon (or other) Postgres project; copy its connection string.
2. Create a Render web service from this repo, using `render.yaml`; supply
   `NAZAR_DATABASE_URL` when prompted.
3. Create a Vercel project from `frontend/`; set `VITE_API_BASE` to the
   Render service's URL.
4. Once the Vercel URL is known, set `NAZAR_CORS_ORIGINS` on Render to that
   exact origin and `NAZAR_ENV=production` (the backend will refuse to
   start otherwise — this is intentional).
5. Verify `GET /ready` returns 200 on the deployed backend before
   considering the deploy live.

Until these steps are run by someone with the relevant accounts, this
project's deployment status is: **configured, not deployed.**
