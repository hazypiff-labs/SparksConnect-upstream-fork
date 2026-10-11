"""Identity providers, one-time codes and transactional mail (audit 2026-10-10, Wave 1).

Rules this module enforces:
  * Provider tokens (Apple, Google) are verified locally against the provider's JWKS: signature, issuer, audience,
    expiry. Only claims from a verified token are trusted — never client-supplied profile fields.
  * An email is "verified" only when the provider says so (`email_verified`) or the user proved it with a code.
  * One-time codes are random, stored only as an HMAC, single-use, short-lived and attempt-limited.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt

logger = logging.getLogger("identity")

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# Expo Go's bundle id: any app running inside Expo Go can mint Apple tokens with this audience, so it is never
# accepted unless explicitly allowed for local development.
EXPO_GO_AUDIENCE = "host.exp.Exponent"

CODE_TTL = timedelta(minutes=15)
CODE_MAX_ATTEMPTS = 5


class ProviderError(Exception):
    pass


def _csv_env(name: str) -> list[str]:
    return [a.strip() for a in os.environ.get(name, "").split(",") if a.strip()]


def apple_audiences() -> list[str]:
    auds = _csv_env("APPLE_AUDIENCES")
    if os.environ.get("ALLOW_EXPO_GO_AUDIENCE") != "1":
        auds = [a for a in auds if a != EXPO_GO_AUDIENCE]
    return auds


def google_client_ids() -> list[str]:
    return _csv_env("GOOGLE_CLIENT_IDS")


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


@dataclass
class ProviderIdentity:
    provider: str  # apple | google
    sub: str
    email: str | None  # lower-cased; None when the token carries no email
    email_verified: bool
    name: str | None = None
    picture: str | None = None


class _Jwks:
    """PyJWKClient with a bounded fetch timeout and its own key cache (one per provider)."""

    def __init__(self, url: str):
        self.client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=5)

    def key_for(self, token: str):
        try:
            return self.client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as exc:
            raise ProviderError(f"signing key: {type(exc).__name__}") from exc
        except jwt.InvalidTokenError as exc:
            raise ProviderError(f"token header: {type(exc).__name__}") from exc


APPLE_JWKS = _Jwks(APPLE_JWKS_URL)
GOOGLE_JWKS = _Jwks(GOOGLE_JWKS_URL)


def verify_apple_token(identity_token: str) -> ProviderIdentity:
    auds = apple_audiences()
    if not auds:
        raise ProviderError("APPLE_AUDIENCES not configured")
    key = APPLE_JWKS.key_for(identity_token)
    try:
        claims = jwt.decode(identity_token, key, algorithms=["RS256"], audience=auds, issuer=APPLE_ISSUER, options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.InvalidTokenError as exc:
        raise ProviderError(type(exc).__name__) from exc
    email = (claims.get("email") or "").strip().lower() or None
    return ProviderIdentity("apple", str(claims["sub"]), email, bool(email) and _truthy(claims.get("email_verified")))


def verify_google_token(id_token: str) -> ProviderIdentity:
    auds = google_client_ids()
    if not auds:
        raise ProviderError("GOOGLE_CLIENT_IDS not configured")
    key = GOOGLE_JWKS.key_for(id_token)
    try:
        claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=auds, options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.InvalidTokenError as exc:
        raise ProviderError(type(exc).__name__) from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise ProviderError("InvalidIssuerError")
    email = (claims.get("email") or "").strip().lower() or None
    return ProviderIdentity("google", str(claims["sub"]), email, bool(email) and _truthy(claims.get("email_verified")), claims.get("name"), claims.get("picture"))


# ---------------------------------------------------------------- one-time codes
def _code_secret() -> bytes:
    return os.environ["JWT_SECRET"].encode()


def hash_code(purpose: str, subject: str, code: str) -> str:
    return hmac.new(_code_secret(), f"{purpose}:{subject}:{code}".encode(), hashlib.sha256).hexdigest()


class CodeStore:
    """`auth_codes`: one live code per (purpose, subject). Subjects are user ids (verify) or emails (reset)."""

    def __init__(self, db: Any):
        self.db = db

    async def ensure_indexes(self) -> None:
        await self.db.auth_codes.create_index([("purpose", 1), ("subject", 1)], unique=True)
        await self.db.auth_codes.create_index("expires_at", expireAfterSeconds=0)

    async def issue(self, purpose: str, subject: str) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = datetime.now(timezone.utc)
        await self.db.auth_codes.update_one(
            {"purpose": purpose, "subject": subject},
            {"$set": {"code_hash": hash_code(purpose, subject, code), "attempts": 0, "created_at": now, "expires_at": now + CODE_TTL}},
            upsert=True,
        )
        return code

    async def consume(self, purpose: str, subject: str, code: str) -> bool:
        """True exactly once for the right code. Wrong guesses burn attempts; the code dies after CODE_MAX_ATTEMPTS."""
        doc = await self.db.auth_codes.find_one_and_update(
            {"purpose": purpose, "subject": subject, "expires_at": {"$gt": datetime.now(timezone.utc)}, "attempts": {"$lt": CODE_MAX_ATTEMPTS}},
            {"$inc": {"attempts": 1}},
        )
        if not doc or not hmac.compare_digest(doc["code_hash"], hash_code(purpose, subject, str(code).strip())):
            return False
        res = await self.db.auth_codes.delete_one({"_id": doc["_id"], "code_hash": doc["code_hash"]})
        return res.deleted_count == 1


# ---------------------------------------------------------------- mail
class Mailer:
    """EMAIL_PROVIDER: `resend` (RESEND_API_KEY + EMAIL_FROM) sends for real; `outbox` stores messages in Mongo
    (`email_outbox`, for development and tests); `log` only logs that a message was produced (never its code).
    Defaults to resend when RESEND_API_KEY is set, otherwise outbox."""

    def __init__(self, db: Any):
        self.db = db

    @property
    def provider(self) -> str:
        return os.environ.get("EMAIL_PROVIDER") or ("resend" if os.environ.get("RESEND_API_KEY") else "outbox")

    async def send(self, to: str, subject: str, text: str, kind: str) -> bool:
        """Never raises: a mail outage must not fail signup halfway or make `forgot` answer differently for
        existing accounts (which would reveal who has one). Returns whether the message was handed off."""
        try:
            return await self._send(to, subject, text, kind)
        except Exception as exc:
            logger.error("mail (%s) not sent: %s", kind, type(exc).__name__)
            return False

    async def _send(self, to: str, subject: str, text: str, kind: str) -> bool:
        provider = self.provider
        if provider == "resend":
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                    json={"from": os.environ.get("EMAIL_FROM", "Date Spark <no-reply@example.com>"), "to": [to], "subject": subject, "text": text},
                )
            if r.status_code >= 400:
                logger.error("mail provider rejected %s message: %s", kind, r.status_code)
                return False
            return True
        if provider == "outbox":
            await self.db.email_outbox.insert_one({"to": to, "subject": subject, "text": text, "kind": kind, "created_at": datetime.now(timezone.utc)})
            return True
        logger.info("mail (%s) for %s… suppressed (EMAIL_PROVIDER=log)", kind, to[:3])
        return False


# ---------------------------------------------------------------- Sign in with Apple token revocation
def apple_revocation_configured() -> bool:
    return all(os.environ.get(k) for k in ("APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY", "APPLE_CLIENT_ID"))


def _apple_client_secret() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": os.environ["APPLE_TEAM_ID"], "iat": now, "exp": now + 300, "aud": APPLE_ISSUER, "sub": os.environ["APPLE_CLIENT_ID"]},
        os.environ["APPLE_PRIVATE_KEY"].replace("\\n", "\n"),
        algorithm="ES256",
        headers={"kid": os.environ["APPLE_KEY_ID"]},
    )


async def _apple_post(path: str, data: dict) -> httpx.Response:  # the only network touch point (patched in tests)
    async with httpx.AsyncClient(timeout=10) as http:
        return await http.post(f"{APPLE_ISSUER}{path}", data=data)


async def apple_exchange_code(authorization_code: str) -> str | None:
    """Authorization code → refresh token (kept only so the grant can be revoked when the account is deleted)."""
    if not apple_revocation_configured():
        return None
    try:
        r = await _apple_post("/auth/token", {"client_id": os.environ["APPLE_CLIENT_ID"], "client_secret": _apple_client_secret(), "code": authorization_code, "grant_type": "authorization_code"})
    except Exception as exc:  # the identity token is already verified — revocation support must never block sign-in
        logger.warning("Apple code exchange error: %s", type(exc).__name__)
        return None
    if r.status_code != 200:
        logger.warning("Apple code exchange failed: %s", r.status_code)
        return None
    return (r.json() or {}).get("refresh_token")


async def apple_revoke(refresh_token: str) -> bool:
    if not apple_revocation_configured():
        return False
    r = await _apple_post("/auth/revoke", {"client_id": os.environ["APPLE_CLIENT_ID"], "client_secret": _apple_client_secret(), "token": refresh_token, "token_type_hint": "refresh_token"})
    if r.status_code != 200:
        logger.error("Apple token revocation failed: %s", r.status_code)
    return r.status_code == 200
