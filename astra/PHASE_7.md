# PHASE 7 — Hardening, End-to-End Validation, Deployment and Honest Reporting

Assumes the repository produced by Phase 6: full stack running, dashboard driven in a browser.

## OBJECTIVE

Prove the whole system works from a clean checkout, close the security and observability
gaps, and produce an evaluation report and a demo path that are true.

## TASKS

1. **Clean-machine reproduction.** Fresh clone into a new directory, follow your own README
   exactly, and record every step where the instructions were wrong or incomplete. Fix them.
   Do not fix the problem in your head and leave the README stale.
2. **Docker Compose** (blueprint Part F): backend, frontend, database, and a pipeline runner.
   `docker compose up` from a clean checkout brings the stack up. No Kubernetes.
3. **Security pass** (blueprint Part L). Verify rather than assume: JWT expiry and refresh
   behaviour; password hashing; RBAC on every endpoint including the ones you added late;
   Pydantic validation on every input; parameterised queries only; rate limiting; audit-log
   completeness; no secrets in git history (check the history, not just the working tree);
   `.env.example` complete and `.env` ignored. Write the results as a checklist with evidence,
   and list what is deliberately out of scope for a hackathon build (a real secrets manager,
   at-rest encryption on a managed volume) rather than implying it is done.
4. **Observability.** Structured logging across pipeline and API; per-stage timings; a
   `/health` endpoint reporting data freshness, last successful run, and validation-failure
   counts. Failures must be findable from logs alone, without a debugger.
5. **End-to-end tests.** At least one test that runs ingestion through to an alert against a
   small fixture corpus committed to the repository — real rows and real (small) attachments,
   not fabricated ones.
6. **Full evaluation run.** Regenerate `reports/evaluation.md` from scratch:
   per-pattern recall, precision@K, per-engine flag rates over the real corpus, the random and
   sort-by-amount baselines, corpus coverage, run date, and the injection seed. Include a
   plainly worded limitations section: two fiscal years of data, ~14% national coverage,
   no ground-truth labels, synthetic validation only, engines whose coverage depends on the
   incomplete sanctioned backfill.
7. **Performance.** Wall-clock for the full pipeline over the whole corpus, broken down by
   stage. Note the largest cost and whether it scales acceptably toward 543 constituencies.
   Optimise only what you measured to be slow.
8. **Documentation.** `README.md` — what NAZAR is, architecture, setup, how to run the
   pipeline, how to run the demo, what the numbers mean and do not mean. Keep
   `docs/DATA_REALITY.md`, `docs/DECISIONS.md` and `docs/STATE.md` current.
9. **Demo script** (blueprint Part Q) — an ordered walkthrough naming *specific real work IDs*
   from the current corpus that you have verified render well: a genuine cross-work duplicate
   pair, a sanction-deadline breach, a cost outlier with its peer distribution, a live
   injection-harness run, and an officer dismissal moving a calibration weight. Every step
   must be one you have actually performed.
10. **Final self-check.** Run the master prompt's self-check protocol in full. Then write the
    closing section of `docs/STATE.md`: what is done, what is partial, what is unverified and
    why. Be specific — "OCR accuracy on handwritten measurement books was not measured" is
    useful; "some things could be improved" is not.

## CONSTRAINTS

- No new features in this phase. If something is missing, note it in `docs/STATE.md`.
- Do not fix a failing test by weakening it.
- Do not claim national coverage, production readiness, or a capability you did not run.

## VALIDATION

- Clean clone → documented setup → `docker compose up` → pipeline run → dashboard loads and
  the demo script completes. All of it performed, with the commands and output recorded.
- `pytest` green with counts and coverage on detector, fusion, scoping and parser code.
- The security checklist completed with evidence per line.
- `reports/evaluation.md` regenerated and read end to end for anything overstated.

## COMPLETION CRITERIA

Every item in the master prompt's DEFINITION OF DONE is satisfied and evidenced, and
`docs/STATE.md` ends with an explicit, specific list of what remains unverified.

## FINAL REPORT TO THE OPERATOR

Deliver: what was built; what was corrected against the blueprint and why, with the evidence;
measured evaluation numbers; performance; what is unverified; what you would do next with more
time; and the exact demo sequence with real work IDs. State the limitations before the
achievements — a Ministry audience will find them anyway, and finding them first is the
difference between a credible system and a demo.
