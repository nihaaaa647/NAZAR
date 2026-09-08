# PHASE 6 — NAZAR District Command Centre (Frontend)

Assumes the repository produced by Phase 5: full pipeline running, API authenticated,
jurisdiction-scoped and tested, alerts and risk cards available over HTTP.

## OBJECTIVE

Build the investigator dashboard — the login-gated command centre where every signal becomes
an officer's next action, and where an MP office, a District Authority, a State Nodal
Authority and the Ministry each get their own account and their own view of the platform at
the aggregation level they are actually entitled to (Non-negotiable #9).

## CONTEXT

Blueprint Part A (frontend), Part J (what a risk card shows), Part K (the review workflow).
React 18 + TypeScript + Vite, Recharts. The name is **NAZAR District Command Centre**; the
word "Nirikshak" must not appear anywhere.

## TASKS

1. Scaffold the Vite + React + TypeScript app under `frontend/`. A typed API client generated
   from or checked against the backend's OpenAPI schema — do not hand-maintain drifting types.
2. **Login screen.** Email/password against `POST /auth/login`, JWT stored, attached to every
   subsequent request. No role selector in the UI — the role and jurisdiction come back from
   the server inside the token and decide everything that renders next. Session expiry
   redirects to login rather than showing an empty or broken screen.
3. Screens:
   - **Dashboard Home** — the landing view differs by role, because the *data returned by
     `/dashboard/summary` and `/works` already differs by role* (Phase 5, task 5a): an
     `mp_office` login lands on its one constituency's risk-ranked feed; `district_authority`
     lands on a district rollup with its constituencies; `state_nodal` lands on a state
     rollup with district drill-down; `ministry` lands on the national-so-far rollup with
     state drill-down. Build one Dashboard Home component parameterised by whatever
     aggregation level the API response actually contains — do not hardcode four separate
     pages, and do not have the frontend decide the aggregation level itself. Filters (state,
     constituency, agency, activity, severity, date) are still available within whatever
     scope the role already has. Every aggregate states its coverage
     ("76 of ~543 constituencies").
   - **Work Detail** — the risk card from blueprint Part J, with evidence tabs: Rules /
     Anomaly / Photos & Documents / Duplicates. Rules tab shows rule name, source (or an
     explicit "unsourced heuristic" marker), the numbers and the peer-group size. Anomaly tab
     shows SHAP contributions. Duplicates tab shows side-by-side images with the evidence
     tier stated in words — "byte-identical file" versus "visually similar, keypoint
     confirmed" versus "visually similar, unconfirmed".
   - **Alerts Queue** — open / assigned / reviewed, sortable, jurisdiction-scoped.
   - **Investigation form** — Confirm / Dismiss / Needs Investigation with a required reason.
   - **Analytics** — fund-utilisation trend and forecast with its confidence band and
     low-confidence label; agency drill-down with volume, amount distribution and flag rate.
   - **Data Health** — corpus coverage, last pipeline run, ingestion validation failures,
     attachment extraction failures.
4. **Navigation and controls also differ by role, not only the data.** An `mp_office` login
   has no state/district filter to misuse, because it has nothing above its own
   constituency to filter — don't render a control whose only function is to prove the
   security boundary by failing loudly when used. `admin` sees a User Management screen
   (list accounts, create/deactivate) and the `POST /feedback` manual weight override; no
   other role does. Build navigation from the same role/scope the API already returned at
   login, so there is one source of truth for "what can this session see", not two.
5. The same components render every role's screens — same `WorkCard`, `RiskBadge`,
   evidence tabs — driven entirely by what the server returns for that session. The
   frontend never filters, hides, or re-scopes data for security; it only decides layout
   and navigation from the role/scope already on the session.
6. Every risk indicator carries a persistent, visible statement that it is a computational
   signal requiring human verification. Synthetic validation cases, if surfaced at all, are
   behind an explicit toggle and are unmistakably labelled on screen.
7. Loading, empty, and error states for every view. A failed API call shows a real message,
   never a blank screen or a silent fallback to stale data. A 401 anywhere sends the session
   back to Login, not to a broken page.

## CONSTRAINTS

- No accusatory language anywhere in the interface. Audit the strings deliberately before
  you finish.
- No fabricated data, no placeholder charts, no lorem ipsum, no hardcoded example works.
  Every number comes from the API.
- Only build a map view if Phase 1 measured enough GPS coverage to justify it and the
  operator approved it; otherwise no mapping library, per the blueprint.
- Keep it legible on a projector at demo resolution. Severity is distinguishable without
  relying on colour alone.

## VALIDATION

- **Run the app in a browser against the live backend and drive it.** Report the screens you
  loaded and what appeared on each. Screenshots are the strongest evidence here.
- Walk the full workflow: land on Home → sort by risk → open a Critical work → read every
  evidence tab → submit a Dismiss with a reason → confirm it persisted via the API → re-run
  fusion → observe the weight change.
- **Log in as all four seeded demo accounts** (`mp_office`, `district_authority`,
  `state_nodal`, `ministry` — from `scripts/seed_users.py`) and, for each, report: what the
  landing view showed, at what aggregation level, and the actual `/dashboard/summary` and
  `/works` response bodies received for that session (not the rendered page — the network
  response). Confirm the four differ in the way task 3/task 5a intended, and that no role's
  session can reach another role's data by any control in the UI.
- Exercise error states: stop the backend and load a page; request a work that does not exist.
- Confirm the production build succeeds, not only the dev server.

## COMPLETION CRITERIA

- All screens (login plus the six investigator screens) render real data from the live API.
- The complete investigator workflow works end to end in a browser and you have driven it
  yourself.
- **All four roles have been logged into and produce visibly, correctly different landing
  views at the correct aggregation level, and the difference is verified from the server's
  actual response, not the rendering.**
- Role scoping is visibly and verifiably enforced by the server.
- Production build succeeds; no console errors on any screen.
- "Nirikshak" appears nowhere; no accusatory string appears anywhere.

## INSPECT BEFORE MOVING ON

Sit through the demo as a judge would: open the dashboard cold and try to find one convincing
case of duplicate evidence in under 60 seconds. If you cannot, the ranking, the filters or the
evidence presentation needs work — that is what the demo lives or dies on.
