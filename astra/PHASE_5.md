# PHASE 5 — Fusion, Alerts, Calibration and the API

Assumes the repository produced by Phase 4: all five detection engines populating
`risk_signal`, duplicate pairs tiered, evaluation report carrying measured per-engine numbers.

## OBJECTIVE

Combine every signal into one explainable score, generate alerts, close the human-feedback
loop, and expose all of it through the FastAPI backend with real authentication and
jurisdiction scoping.

## CONTEXT

Blueprint Part B Engines 7 and 8, Part E (API), Part I (hybrid resolution), Part J
(explainability), Part K (human-in-the-loop), Part L (security).

## TASKS

1. **Engine 7 — Risk Fusion** (`ml/fusion/`). Weighted sum over normalised signals, with a
   severity floor: any near-certain signal (Tier-1 byte-identical cross-work duplicate, a
   confirmed cross-year duplicate claim, a confirmed Rule 163 cluster) forces the band to
   Critical regardless of quiet signals elsewhere. Bands: 0-30 Low, 31-60 Moderate,
   61-80 High, 81-100 Critical. Initial weights are expert-set from CAG severity ranking and
   recorded with their rationale. Output `risk_score`, `severity_band`, and
   `contributing_signals[]` where each entry names the engine, its normalised value, its
   weight and its contribution.
2. **Explainability assembly** (blueprint Part J). For each flagged work, build the officer's
   card server-side: WHAT happened, WHY (reason per signal, with real numbers and the peer
   group's size), WHICH evidence (attachment thumbnails, duplicate pairs with their tier,
   the exact rule text and source where one exists), HOW unusual (percentile against the real
   peer distribution), WHICH related entities (same agency's other flagged works), WHAT to
   investigate (a suggested action derived from which signals fired). Nothing on this card
   may be a bare probability, and nothing may accuse.
3. **Alerts.** `risk_score >= 61` creates an alert row with severity and status
   (open/assigned/reviewed). Re-running the pipeline updates rather than duplicating alerts.
4. **Engine 8 — Human-Feedback Calibration** (`ml/calibration/`). Per-engine confirm/dismiss
   rate over a rolling window; bounded weight nudge (±10% per cycle) applied only after a
   minimum of 10 decisions for that engine. A dismissal adjusts a weight; it never deletes or
   suppresses the underlying signal, and the audit trail keeps everything. Seed a small set
   of demo decisions so the mechanic is demonstrable.
5. **Backend** (`backend/app/`). FastAPI, Pydantic schemas, SQLAlchemy repositories, every
   endpoint in blueprint Part E. JWT auth (`python-jose`, `passlib`). RBAC middleware scoping
   every query by the caller's `jurisdiction_scope` **in the query layer**, never in the UI.
   Roles: mp_office, state_nodal, district_authority, ministry, admin. `audit_log` rows for
   every sensitive read and every investigation decision. Structured logging. Rate limiting.
   OpenAPI docs available at `/docs`.
5a. **User accounts and jurisdiction scoping — the problem statement names four distinct
   audiences (MP, State Nodal Authority, District Authority, Ministry) and each one gets a
   real account, not a role switcher.** (Non-negotiable #9.)
   - `user_account`: `id`, `name`, `email`, `password_hash`, `role`
     (`mp_office | state_nodal | district_authority | ministry | admin`),
     `jurisdiction_scope` (a structured value naming exactly what that row is allowed to
     see — a constituency id for `mp_office`, a district for `district_authority`, a state
     for `state_nodal`, nothing/all for `ministry`). Design the scope representation so a
     single repository-layer filter function can apply it to every query — do not
     special-case each role's filter logic per endpoint.
   - `POST /auth/login` issues a JWT carrying `role` and `jurisdiction_scope`. Every
     other endpoint's repository layer reads those claims and filters — it does not trust
     any jurisdiction value the client sends in a query parameter or body.
   - Account creation is `admin`-only (no public self-registration — these are government
     credentials). Provide a seed script, `scripts/seed_users.py`, that creates exactly one
     demo account per role (`mp_office`, `district_authority`, `state_nodal`, `ministry`,
     `admin`), each bound to a **real** jurisdiction present in the ingested corpus (an
     actual constituency/district/state/MP name from the scraped data, not a placeholder).
     Print the demo credentials it created so they can be used for the Phase 6/7 demo.
   - `GET /dashboard/summary` and every list/aggregate endpoint must compute its
     aggregation level from the caller's role: `mp_office` returns that one constituency;
     `district_authority` aggregates its constituencies; `state_nodal` aggregates its
     districts; `ministry` aggregates every state ingested so far (labelled with actual
     coverage, per Correction 10). This is a backend responsibility — the frontend in
     Phase 6 renders whatever aggregation the API already computed, it does not
     recompute or re-filter anything client-side.
6. **Pipeline orchestration.** `pipelines/run_pipeline.py` runs ingest → attachments →
   features → engines → fusion → alerts end to end, idempotently, with progress output and
   per-stage timing. Scheduling via APScheduler or cron as the blueprint specifies — no
   message queue.

## CONSTRAINTS

- No raw SQL string interpolation anywhere; parameterised ORM queries only.
- Jurisdiction scoping is enforced server-side in the repository layer. Assume a hostile
  client.
- The synthetic-isolation guarantee from Phase 2 must still hold through the API. Prove it
  again here with an API-level test.
- Fusion must be pure and unit-testable: given a set of signals, the score is deterministic.
- Weight changes are capped, logged, attributable and reversible.
- `.env` for configuration; nothing secret is committed.

## VALIDATION

- Unit tests: fusion arithmetic; severity-floor override; band boundaries; calibration cap;
  the minimum-decisions gate.
- Integration tests against a running app: every endpoint, happy path plus 401, 403, 404 and
  a 422 validation failure.
- **A jurisdiction test that proves a district_authority user receives 403 or an empty set for
  another district's works** — write it, and confirm it fails when you deliberately remove the
  scoping.
- **One test per role** (`mp_office`, `district_authority`, `state_nodal`, `ministry`) proving
  `GET /works` and `GET /dashboard/summary` return exactly the aggregation level that role is
  entitled to — a constituency-scoped count for `mp_office`, correctly larger counts for
  `district_authority` < `state_nodal` < `ministry` on the same underlying corpus — and that
  no role can widen its own scope by passing a different jurisdiction value in the request.
- Run `scripts/seed_users.py`; confirm the four demo accounts exist and each logs in
  successfully via `POST /auth/login`.
- An API-level test that a synthetic work never appears in a default `/works` response.
- Real requests: start the server, exercise the endpoints, paste real response bodies into
  your report.
- Full pipeline run end to end over the real corpus; per-stage timings recorded; alert count
  and severity distribution reported.
- Feed a Confirm and a Dismiss through `POST /investigations`, then show the calibration
  weight actually moving on the next fusion run.

## COMPLETION CRITERIA

- One command runs the whole pipeline from raw CSVs to alerts.
- Every Part E endpoint exists, is authenticated, jurisdiction-scoped and tested.
- Risk cards assemble server-side with complete, honest, non-accusatory explanations.
- The calibration loop demonstrably closes.
- `reports/evaluation.md` now includes fused precision@Top-K against the baselines.
- Four seeded demo accounts exist (one per role, real jurisdictions), each returns a
  correctly scoped, correctly aggregated response, and no role can escalate its own scope.

## INSPECT BEFORE MOVING ON

Take the top 10 works by fused risk score and read each card as though you were the officer
receiving it. Would you open an inquiry? If a card is unconvincing, the problem is in the
weights, the explanation assembly or an upstream engine — find which, and fix it before
building a UI on top of it.
