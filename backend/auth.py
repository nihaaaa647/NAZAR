"""Real authentication: Argon2id password hashing + signed, expiring JWTs.

Replaces Phase 1's plaintext-compare + hand-rolled HMAC token (backend/main.py
used to hold both directly) with a maintained library on each side -
`argon2-cffi` for hashing, `PyJWT` for the token. Secrets come only from
environment variables (NAZAR_AUTH_SECRET); nothing here ever logs a password
or a full token (callers log at most a token's jti - see backend/main.py's
audit_event calls)."""
from __future__ import annotations

import os
import secrets
import time
import uuid
import warnings

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash

ALGORITHM = 'HS256'
# NAZAR_ENV=production is a hard gate (Phase 3 mandatory safeguard #4): an
# unset NAZAR_AUTH_SECRET must fail startup outright rather than quietly
# minting a secret every process would sign differently. Any other value
# (default: unset/'development') allows the ephemeral random secret, but
# never silently - a clear warning is emitted so it shows up in process logs.
_env = os.environ.get('NAZAR_ENV', 'development')
_explicit_secret = os.environ.get('NAZAR_AUTH_SECRET')
if _env == 'production' and not _explicit_secret:
    raise RuntimeError('NAZAR_AUTH_SECRET must be set when NAZAR_ENV=production - '
                        'refusing to start with a random per-process secret in production.')
if not _explicit_secret:
    warnings.warn('NAZAR_AUTH_SECRET is not set - using a random secret generated for this process only. '
                   'Every other backend process (a second worker, a restart) will reject this process’s '
                   'tokens. Fine for a single local demo process; set NAZAR_AUTH_SECRET explicitly for anything else.',
                   stacklevel=2)
AUTH_SECRET = _explicit_secret or secrets.token_urlsafe(32)
TOKEN_TTL = int(os.environ.get('NAZAR_TOKEN_TTL', '28800'))  # 8h demo session

_hasher = PasswordHasher()


def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(password_hash: str, plaintext: str) -> bool:
    try:
        return _hasher.verify(password_hash, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False


def create_token(user_id: str, persona_id: str, role: str, *, ttl: int = TOKEN_TTL) -> tuple[str, str, int]:
    """Returns (token, jti, expires_at_epoch). jti lets a specific token be
    revoked (logout) without invalidating every other session for the user."""
    now = int(time.time())
    jti = uuid.uuid4().hex
    exp = now + ttl
    claims = {'sub': user_id, 'persona_id': persona_id, 'role': role, 'iat': now, 'exp': exp, 'jti': jti}
    token = jwt.encode(claims, AUTH_SECRET, algorithm=ALGORITHM)
    return token, jti, exp


class TokenError(Exception):
    """Raised with a short, audit-safe reason - never includes the token itself."""


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, AUTH_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenError('expired')
    except jwt.InvalidTokenError:
        raise TokenError('invalid')
