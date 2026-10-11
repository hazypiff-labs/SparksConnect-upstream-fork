"""Regression tests for the fusion-panel re-review of the remediation diff (2026-10-11)."""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import identity
import limits
import recommend
import server
from conftest import rebind_server_db
from test_security_auth import apple_token, KEY


@pytest.fixture(scope="module")
def c():
    from fake_app import fake_llm_complete

    real = recommend.llm_complete
    recommend.llm_complete = fake_llm_complete
    identity.APPLE_JWKS.key_for = lambda t: KEY.public_key()
    rebind_server_db()
    with TestClient(server.app) as client:
        yield client
    recommend.llm_complete = real


def run(c, coro):
    return c.portal.call(lambda: coro)


def email():
    return f"r2{uuid.uuid4().hex[:10]}@example.com"


def test_mail_outage_never_breaks_signup_or_reveals_accounts(c, monkeypatch):
    async def down(*a, **k):
        raise ConnectionError("smtp down")

    monkeypatch.setattr(server.mailer, "_send", down)
    addr = email()
    r = c.post("/api/auth/signup", json={"name": "M", "email": addr, "password": "Password123!"})
    assert r.status_code == 200  # account created AND the client gets its token
    known = c.post("/api/auth/password/forgot", json={"email": addr})
    unknown = c.post("/api/auth/password/forgot", json={"email": email()})
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()


def test_apple_code_exchange_failure_does_not_block_sign_in(c, monkeypatch):
    async def boom(path, data):
        raise TimeoutError("apple slow")

    monkeypatch.setattr(identity, "_apple_post", boom)
    monkeypatch.setattr(identity, "apple_revocation_configured", lambda: True)
    monkeypatch.setattr(identity, "_apple_client_secret", lambda: "secret")
    r = c.post("/api/auth/apple", json={"identity_token": apple_token("x-" + uuid.uuid4().hex, email()), "authorization_code": "c"})
    assert r.status_code == 200


def test_legacy_deleted_apple_account_released_at_startup(c):
    sub = "legacy-" + uuid.uuid4().hex
    run(c, server.db.users.insert_one({"id": str(uuid.uuid4()), "email": f"deleted-{uuid.uuid4()}@deleted.local", "apple_sub": sub, "deleted_at": datetime.now(timezone.utc)}))
    run(c, server.startup())
    r = c.post("/api/auth/apple", json={"identity_token": apple_token(sub, email())})
    assert r.status_code == 200


def test_legacy_fully_revealed_surprise_stays_unlocked_for_viewers(c):
    sid = str(uuid.uuid4())
    future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    run(c, server.db.sparks.insert_one({"id": sid, "owner_type": "guest", "owner_id": "g-legacy", "title": "T", "surprise": True, "scheduled_at": future,
                                        "revealed_steps": 3, "activities": [{"activity_name": a} for a in "abc"], "created_at": datetime.now(timezone.utc)}))
    out = c.get(f"/api/shared/{sid}").json()
    assert out["locked_for_recipient"] is False and len(out["activities"]) == 3


def test_rejected_attempts_do_not_inflate_counters(c):
    key = "test:" + uuid.uuid4().hex
    lim = server.limiter
    results = [run(c, lim.hit(key, 2, timedelta(hours=1))) for _ in range(6)]
    assert results == [True, True, False, False, False, False]
    assert run(c, lim.hit(key, 3, timedelta(hours=1))) is True  # raising the cap works immediately


def test_413_still_carries_cors_headers(c):
    r = c.post("/api/events", content=json.dumps({"event": "app_opened", "props": {"x": "A" * 70_000}}),
               headers={"Content-Type": "application/json", "Origin": "https://app.example.com", "X-Guest-ID": "g_" + uuid.uuid4().hex})
    assert r.status_code == 413 and r.headers.get("access-control-allow-origin") in ("*", "https://app.example.com")


def test_llm_deadline_covers_the_retry():
    assert recommend.LLM_MAX_RETRIES >= 1
    # asyncio.wait_for deadline in llm_complete = per-attempt timeout × attempts + slack
    assert recommend.LLM_TIMEOUT_SECONDS * (recommend.LLM_MAX_RETRIES + 1) + 5 <= 120  # app waits 120 s


@pytest.mark.parametrize("tags", [{"a": 1}, 5, "romantic", None])
def test_malformed_vibe_tags_never_crash(monkeypatch, tags):
    async def fake(system, prompt, model):
        return json.dumps({"sparks": [{"title": "T", "vibe_tags": tags, "activities": []}]})

    async def none(*a):
        return []

    monkeypatch.setattr(recommend, "llm_complete", fake)
    monkeypatch.setattr(recommend, "gather_venues", none)
    sparks = asyncio.run(recommend.generate_sparks(relationship_type="partner", vibes=["fun"], budget="under25", distance="10", location={}, exclude_titles=[], history={}, date_label=None, time_label=None, ai_settings={}))
    assert sparks[0]["vibe_tags"] == ([] if not isinstance(tags, list) else tags)


def test_places_budget_guard_failure_means_no_paid_call():
    import places

    async def broken():
        raise RuntimeError("db down")

    places.set_budget_guard(broken)
    try:
        assert asyncio.run(places._within_budget()) is False
    finally:
        places.set_budget_guard(None)
