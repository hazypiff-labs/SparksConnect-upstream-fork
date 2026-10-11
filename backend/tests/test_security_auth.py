"""Audit 2026-10-10 Wave 1 — identity & auth regression tests (in-process app, real MongoDB).

Apple / Google tokens are signed with a locally generated RSA key that stands in for the provider's JWKS, so every
verification step except the key download runs for real (signature, issuer, audience, expiry, claims).
"""
import asyncio
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import identity
import recommend
import server
from conftest import rebind_server_db

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
APPLE_AUD = os.environ["APPLE_AUDIENCES"].split(",")[0]
GOOGLE_AUD = os.environ["GOOGLE_CLIENT_IDS"].split(",")[0]
ADMIN_EMAIL = os.environ["SPARKS_TEST_ADMIN_EMAIL"]


def apple_token(sub, email=None, verified=True, aud=APPLE_AUD, iss="https://appleid.apple.com", exp_in=600):
    claims = {"iss": iss, "aud": aud, "sub": sub, "iat": int(time.time()), "exp": int(time.time()) + exp_in}
    if email:
        claims.update(email=email, email_verified="true" if verified else "false")
    return jwt.encode(claims, KEY, algorithm="RS256")


def google_token(sub, email, verified=True, aud=GOOGLE_AUD):
    claims = {"iss": "https://accounts.google.com", "aud": aud, "sub": sub, "email": email, "email_verified": verified, "iat": int(time.time()), "exp": int(time.time()) + 600, "name": "G User"}
    return jwt.encode(claims, KEY, algorithm="RS256")


@pytest.fixture(scope="module")
def c():
    identity.APPLE_JWKS.key_for = lambda t: KEY.public_key()
    identity.GOOGLE_JWKS.key_for = lambda t: KEY.public_key()
    rebind_server_db()
    with TestClient(server.app) as client:
        yield client


def run(c, coro):
    """Run a coroutine on the TestClient's event loop (Motor is bound to it)."""
    return c.portal.call(lambda: coro)


def outbox_code(c, to, kind):
    doc = run(c, server.db.email_outbox.find_one({"to": to, "kind": kind}, sort=[("created_at", -1)]))
    assert doc, f"no {kind} mail for {to}"
    return doc["text"].split("code is ")[1][:6]


def email():
    return f"u{uuid.uuid4().hex[:10]}@example.com"


def signup(c, addr, pw="Password123!"):
    r = c.post("/api/auth/signup", json={"name": "U", "email": addr, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------- C1: Apple account takeover
def test_apple_client_supplied_email_is_ignored(c):
    r = c.post("/api/auth/apple", json={"identity_token": apple_token("attacker-" + uuid.uuid4().hex), "email": ADMIN_EMAIL})
    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert u["role"] == "user" and u["email"] != ADMIN_EMAIL and u["email"].endswith("@users.invalid")


def test_apple_unverified_email_claim_never_links(c):
    target = email()
    signup(c, target)
    r = c.post("/api/auth/apple", json={"identity_token": apple_token("sub-" + uuid.uuid4().hex, target, verified=False)})
    assert r.status_code == 200 and r.json()["user"]["email"] != target


def test_apple_verified_email_links_verified_account(c):
    addr = email()
    acct = signup(c, addr)
    code = outbox_code(c, addr, "verify_email")
    assert c.post("/api/auth/verify-email/confirm", json={"code": code}, headers=bearer(acct["access_token"])).json()["email_verified"]
    r = c.post("/api/auth/apple", json={"identity_token": apple_token("sub-" + uuid.uuid4().hex, addr)})
    assert r.json()["user"]["id"] == acct["user"]["id"]
    # the password still works for a verified owner
    assert c.post("/api/auth/login", json={"email": addr, "password": "Password123!"}).status_code == 200


@pytest.mark.parametrize("bad", [
    {"aud": "host.exp.Exponent"},  # Expo Go audience — any Expo Go app can mint these
    {"aud": "com.someone.else"},
    {"iss": "https://evil.example.com"},
    {"exp_in": -60},
])
def test_apple_token_claims_are_enforced(c, bad):
    r = c.post("/api/auth/apple", json={"identity_token": apple_token("s-" + uuid.uuid4().hex, **bad)})
    assert r.status_code == 401


def test_apple_token_signed_by_other_key_rejected(c):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tok = jwt.encode({"iss": "https://appleid.apple.com", "aud": APPLE_AUD, "sub": "x", "iat": int(time.time()), "exp": int(time.time()) + 600}, other, algorithm="RS256")
    assert c.post("/api/auth/apple", json={"identity_token": tok}).status_code == 401


# ---------------------------------------------------------------- N1: email squatting
def test_squatted_unverified_account_is_claimed_by_verified_google_owner(c):
    victim = email()
    squat = signup(c, victim, pw="AttackerPass1!")  # attacker registers the victim's address, never verifies it
    r = c.post("/api/auth/google", json={"id_token": google_token("g-" + uuid.uuid4().hex, victim)})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == squat["user"]["id"] and r.json()["user"]["email_verified"]
    # attacker's password and existing session are both dead
    assert c.post("/api/auth/login", json={"email": victim, "password": "AttackerPass1!"}).status_code == 401
    assert c.get("/api/auth/me", headers=bearer(squat["access_token"])).status_code == 401
    assert c.get("/api/auth/me", headers=bearer(r.json()["access_token"])).status_code == 200


def test_google_unverified_email_does_not_link(c):
    addr = email()
    acct = signup(c, addr)
    r = c.post("/api/auth/google", json={"id_token": google_token("g-" + uuid.uuid4().hex, addr, verified=False)})
    assert r.status_code == 200 and r.json()["user"]["id"] != acct["user"]["id"]


def test_google_wrong_audience_rejected(c):
    assert c.post("/api/auth/google", json={"id_token": google_token("g", email(), aud="someone-else")}).status_code == 401


def test_google_same_sub_returns_same_user(c):
    sub, addr = "g-" + uuid.uuid4().hex, email()
    a = c.post("/api/auth/google", json={"id_token": google_token(sub, addr)}).json()["user"]["id"]
    b = c.post("/api/auth/google", json={"id_token": google_token(sub, addr)}).json()["user"]["id"]
    assert a == b


# ---------------------------------------------------------------- M2/M3 races & deletion
def test_concurrent_duplicate_signup_never_500(c):
    addr = email()
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda _: c.post("/api/auth/signup", json={"name": "R", "email": addr, "password": "Password123!"}).status_code, range(8)))
    assert sorted(set(codes)) in ([200, 409], [200]) and codes.count(200) == 1


def test_deleted_apple_user_can_sign_up_again_and_data_is_gone(c, monkeypatch):
    calls = []

    async def fake_post(path, data):
        calls.append(path)
        return type("R", (), {"status_code": 200, "json": lambda self: {"refresh_token": "rt-1"}})()

    monkeypatch.setattr(identity, "_apple_post", fake_post)
    for k in ("APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_CLIENT_ID"):
        monkeypatch.setenv(k, "x")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    monkeypatch.setenv("APPLE_PRIVATE_KEY", pem)

    sub = "del-" + uuid.uuid4().hex
    first = c.post("/api/auth/apple", json={"identity_token": apple_token(sub, email()), "authorization_code": "code-1"}).json()
    h = bearer(first["access_token"])
    assert c.put("/api/users/me/preferences", json={"favorite_vibes": ["fun"]}, headers=h).status_code == 200
    assert c.delete("/api/auth/account", headers=h).json() == {"ok": True}
    assert calls == ["/auth/token", "/auth/revoke"]  # grant exchanged at sign-in, revoked at deletion
    assert c.get("/api/auth/me", headers=h).status_code == 401
    assert run(c, server.db.user_preferences.count_documents({"owner_id": first["user"]["id"]})) == 0
    again = c.post("/api/auth/apple", json={"identity_token": apple_token(sub, email())})
    assert again.status_code == 200 and again.json()["user"]["id"] != first["user"]["id"]


# ---------------------------------------------------------------- M4: throttling, verification, reset
def test_login_is_throttled_per_email(c):
    addr = email()
    signup(c, addr)
    admin = bearer(c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": os.environ["SPARKS_TEST_ADMIN_PASSWORD"]}).json()["access_token"])
    before = c.get("/api/admin/config", headers=admin).json()["limits"]["auth_login_email_hourly"]
    c.put("/api/admin/config", headers=admin, json={"limits": {"auth_login_email_hourly": 3}})
    try:
        codes = [c.post("/api/auth/login", json={"email": addr, "password": "wrong-password"}).status_code for _ in range(5)]
        assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    finally:
        c.put("/api/admin/config", headers=admin, json={"limits": {"auth_login_email_hourly": before}})


def test_email_verification_wrong_code_and_attempt_limit(c):
    addr = email()
    acct = signup(c, addr)
    h = bearer(acct["access_token"])
    assert acct["user"]["email_verified"] is False
    real = outbox_code(c, addr, "verify_email")
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        assert c.post("/api/auth/verify-email/confirm", json={"code": wrong}, headers=h).status_code == 400
    # attempts exhausted: even the right code is now refused until a new one is requested
    assert c.post("/api/auth/verify-email/confirm", json={"code": real}, headers=h).status_code == 400
    assert c.post("/api/auth/verify-email/request", headers=h).status_code == 200
    fresh = outbox_code(c, addr, "verify_email")
    assert c.post("/api/auth/verify-email/confirm", json={"code": fresh}, headers=h).json()["email_verified"] is True


def test_password_reset_flow_revokes_old_sessions(c):
    addr = email()
    acct = signup(c, addr, pw="OldPassword1!")
    # unknown address: identical response, no mail
    assert c.post("/api/auth/password/forgot", json={"email": email()}).json() == {"ok": True}
    assert c.post("/api/auth/password/forgot", json={"email": addr}).json() == {"ok": True}
    code = outbox_code(c, addr, "reset_password")
    assert c.post("/api/auth/password/reset", json={"email": addr, "code": "999999" if code != "999999" else "888888", "new_password": "NewPassword1!"}).status_code == 400
    r = c.post("/api/auth/password/reset", json={"email": addr, "code": code, "new_password": "NewPassword1!"})
    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
    assert c.get("/api/auth/me", headers=bearer(acct["access_token"])).status_code == 401
    assert c.post("/api/auth/login", json={"email": addr, "password": "OldPassword1!"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": addr, "password": "NewPassword1!"}).status_code == 200
    # a code works once
    assert c.post("/api/auth/password/reset", json={"email": addr, "code": code, "new_password": "Another1!x"}).status_code == 400


# ---------------------------------------------------------------- N11 / M6
def test_admin_seed_never_promotes_existing_account(c, monkeypatch):
    addr = email()
    acct = signup(c, addr)
    monkeypatch.setenv("ADMIN_EMAIL", addr)
    monkeypatch.setenv("ADMIN_PASSWORD", "whatever-123")
    run(c, server.startup())
    assert c.get("/api/auth/me", headers=bearer(acct["access_token"])).json()["role"] == "user"


def test_generation_failure_message_is_generic(c, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("internal detail: mongodb://secret-host:27017")

    monkeypatch.setattr(recommend, "llm_complete", boom)
    r = c.post("/api/sparks/generate", headers={"X-Guest-ID": "guest-" + uuid.uuid4().hex[:12]},
               json={"relationship_type": "partner", "vibes": ["romantic"], "budget": "under25", "distance": "10", "location": {"label": "X", "lat": 40.0, "lng": -74.0}})
    assert r.status_code == 502 and "secret-host" not in r.text
