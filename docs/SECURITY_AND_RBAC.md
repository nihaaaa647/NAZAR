# NAZAR — Security and RBAC verification

_As of 2026-09-28 (Phase 5 section E/G.7). Every claim below is a specific
file/test, not a general assertion — check the reference if you doubt it._

## Authentication

- **Argon2id** password hashing (`argon2-cffi`), never plaintext compare —
  `backend/auth.py: hash_password`/`verify_password`.
- **Signed, expiring JWT** (`PyJWT`, HS256), 8h TTL by default
  (`NAZAR_TOKEN_TTL`), carrying user id / persona id / role / a `jti` that
  `/auth/logout` can revoke (`revoked_tokens` table). Never a role/
  jurisdiction the client can influence — decoded server-side on every
  request (`current_persona`).
- **Timing-safe login**: an unknown `user_id` is checked against a fixed
  dummy Argon2 hash so an account's existence can't be inferred from
  response timing (`backend/main.py: login`).
- **Production fails to start without `NAZAR_AUTH_SECRET`**
  (`backend/auth.py`, `NAZAR_ENV=production` gate) — verified by
  `tests/test_production_security.py::test_production_without_auth_secret_refuses_to_start`.
- **Login rate limiting**: 10 attempts / 5 minutes per client IP, 429 past
  that (`backend/main.py: _check_login_rate_limit`) — verified by
  `tests/test_production_security.py::test_login_rate_limit_blocks_after_max_attempts`.
  Known limitation: single-process in-memory, see `docs/KNOWN_LIMITATIONS.md`.

## Authorization (jurisdiction RBAC)

- **Default-deny**: a persona's `filter` dict must match every field it
  names; an *empty* filter (Ministry) is what grants national access — not
  an admin flag (`backend/main.py: filter_matches`).
- **Enforced server-side on every protected endpoint**, at the query/scope
  layer, never left to the frontend to hide — `scope_works`, `scope_cases`,
  `scope_quality_alerts`, `scope_image_matches`, etc., each independently
  apply the same `filter_matches`.
- **Image-match pairs require BOTH works in scope** (Phase 4 H) — a
  cross-jurisdiction pair is refused, not partially shown —
  `tests/test_image_matches_api.py`.
- **A forged persona claim in the request body is ignored** — persona/role
  come only from the verified token, never a body field —
  `tests/test_auth_rbac.py::test_direct_api_bypass_attempt_via_forged_persona_claim_fails`.
- **Access denials are audited**: `require_case_scope`/equivalent record an
  `access_denied` audit event before raising 403.

## Production hardening (Phase 5 section E)

| Check | Status | Reference |
|---|---|---|
| Production fails without `NAZAR_AUTH_SECRET` | ✅ enforced | `backend/auth.py` |
| Argon2id passwords | ✅ | `backend/auth.py` |
| Tokens expire, can't change role/jurisdiction | ✅ | `backend/auth.py`, `current_persona` |
| Backend enforces every scope | ✅ | every `scope_*` function, RBAC test suite |
| CORS: production requires an explicit origin | ✅ enforced (new, Phase 5) | `backend/main.py`, `test_production_with_auth_secret_but_wildcard_cors_refuses_to_start` |
| Login rate limiting | ✅ (new, Phase 5) | `_check_login_rate_limit`, single-process limitation documented |
| Request-size limits | ✅ (new, Phase 5) | `MAX_REQUEST_BODY_BYTES=1MB` middleware, `test_oversized_request_body_is_rejected` |
| Safe file handling / path traversal | ✅ | `/image/{work_id}/{filename}` (allowlist), `/satellite/image/{asset_id}/{tag}` (allowlist + `is_relative_to`, fixed in Phase 5 — see `docs/DECISIONS.md`) |
| SSRF protection | ✅ by absence | no endpoint accepts a server-fetched URL; see `docs/KNOWN_LIMITATIONS.md` |
| Secure error responses | ✅ | HTTPException bodies never include stack traces or file paths |
| No secrets/tokens in logs | ✅ | `audit_event` never logs a password or full token, only a `jti` |
| No dev credentials in the frontend bundle | ✅ | demo credentials documented in `README.md` only, never shipped in `frontend/src/App.tsx` |
| Dependency vulnerability review | ⚠️ not run | no network access to a CVE database in this environment — see `docs/KNOWN_LIMITATIONS.md` |
| Security headers | ✅ (new, Phase 5) | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` middleware |

## Audit logging

Every login (success/failure), logout, access denial, reviewer decision,
escalation, and image-match review appends an immutable row via
`audit_event()` — `user_id`, `persona_id`, `role`, `entity_type`/`entity_id`,
`action`, `reason`, before/after state where relevant, `success`, timestamp.
Never a password or full token. `GET /audit` is Ministry-only
(`tests/test_auth_rbac.py::test_audit_endpoint_is_ministry_only`).
