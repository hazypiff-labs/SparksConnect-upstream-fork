"""Audit 2026-10-10 Wave 2 — cost controls, input bounds and entitlement-integrity regression tests."""
import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

import places
import recommend
import server
from conftest import rebind_server_db
from entitlements import LookupFailure
from test_server_entitlements import D, NOW, Env, deliver, event

BODY = {"relationship_type": "partner", "vibes": ["romantic"], "budget": "under25", "distance": "10", "location": {"label": "Home", "lat": 40.0, "lng": -74.0}}


@pytest.fixture(scope="module")
def c():
    from fake_app import fake_llm_complete

    real = recommend.llm_complete
    recommend.llm_complete = fake_llm_complete
    rebind_server_db()
    with TestClient(server.app) as client:
        yield client
    recommend.llm_complete = real


@pytest.fixture(scope="module")
def admin(c):
    import os

    tok = c.post("/api/auth/login", json={"email": os.environ["SPARKS_TEST_ADMIN_EMAIL"], "password": os.environ["SPARKS_TEST_ADMIN_PASSWORD"]}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def config(c, admin):
    """Temporarily change admin config (limits / features); restores the previous values afterwards."""
    before = c.get("/api/admin/config", headers=admin).json()
    changed: dict = {}

    def set_(limits=None, features=None):
        body = {}
        if limits:
            body["limits"] = limits
            changed.setdefault("limits", {}).update({k: before["limits"][k] for k in limits})
        if features:
            body["features"] = features
            changed.setdefault("features", {}).update({k: before["features"].get(k, True) for k in features})
        assert c.put("/api/admin/config", headers=admin, json=body).status_code == 200

    yield set_
    if changed:
        c.put("/api/admin/config", headers=admin, json=changed)


def guest():
    return {"X-Guest-ID": "guest-" + uuid.uuid4().hex[:16]}


# ---------------------------------------------------------------- H1: forged proxy headers
def test_spoofed_cf_header_does_not_escape_ip_caps(c, config):
    config(limits={"ip_hourly_cap": 3, "ip_daily_cap": 1000, "guest_ids_per_ip_daily": 1000})
    codes = [c.post("/api/sparks/generate", json=BODY, headers={**guest(), "CF-Connecting-IP": f"10.77.0.{i}"}).status_code for i in range(5)]
    assert codes.count(429) >= 2, codes


# ---------------------------------------------------------------- H2: geocode
def test_geocode_needs_identity_bounds_input_throttles_and_caches(c, config, monkeypatch):
    calls = []

    async def fake_geocode(q):
        calls.append(q)
        return {"label": "Austin", "lat": 30.27, "lng": -97.74}

    monkeypatch.setattr(server, "geocode", fake_geocode)
    assert c.get("/api/places/geocode", params={"q": "Austin"}).status_code == 400  # no identity
    assert c.get("/api/places/geocode", params={"q": "x" * 121}, headers=guest()).status_code == 422
    config(limits={"geocode_ip_hourly": 3})
    q = "austin " + uuid.uuid4().hex[:6]
    first = c.get("/api/places/geocode", params={"q": q}, headers=guest())
    second = c.get("/api/places/geocode", params={"q": q.upper()}, headers=guest())
    assert first.status_code == second.status_code == 200 and len(calls) == 1  # second answered from cache
    c.get("/api/places/geocode", params={"q": "x" + q}, headers=guest())
    assert c.get("/api/places/geocode", params={"q": "y" + q}, headers=guest()).status_code == 429


# ---------------------------------------------------------------- H4/H5: input bounds
@pytest.mark.parametrize("patch", [
    {"occasion": "Z" * 400_00},
    {"vibes": ["fun"] * 50},
    {"relationship_type": "p" * 100},
    {"exclude_titles": ["t"] * 200},
    {"location": {"label": "L", "lat": 999, "lng": 0}},
])
def test_generate_rejects_oversized_or_invalid_fields(c, patch):
    assert c.post("/api/sparks/generate", json={**BODY, **patch}, headers=guest()).status_code == 422


def test_request_body_cap(c):
    r = c.post("/api/events", content=json.dumps({"event": "app_opened", "props": {"x": "A" * 70_000}}), headers={**guest(), "Content-Type": "application/json"})
    assert r.status_code == 413


def test_events_allowlist_and_props_cap(c):
    h = guest()
    assert c.post("/api/events", json={"event": "app_opened", "props": {"screen": "home"}}, headers=h).status_code == 200
    for name in ("sparks_generated", "entitlement_verified", "spark_shared", "anything"):
        assert c.post("/api/events", json={"event": name, "props": {}}, headers=h).status_code == 422
    assert c.post("/api/events", json={"event": "app_opened", "props": {"x": "A" * 3000}}, headers=h).status_code == 422


def test_location_extra_keys_are_dropped(c):
    h = guest()
    body = {**BODY, "location": {"label": "Home", "lat": 40.0, "lng": -74.0, "home_address": "12 Private St"}}
    sid = c.post("/api/sparks/generate", json=body, headers=h).json()["sparks"][0]["id"]
    doc = erun_db(c, server.db.sparks.find_one({"id": sid}, {"_id": 0, "location": 1}))
    assert doc["location"] == {"label": "Home", "lat": 40.0, "lng": -74.0}


def erun_db(c, coro):
    return c.portal.call(lambda: coro)


# ---------------------------------------------------------------- N9/N10: kill switch, global ceiling, refunds
def test_generation_kill_switch(c, config):
    config(features={"generation_enabled": False})
    assert c.post("/api/sparks/generate", json=BODY, headers=guest()).status_code == 503


def test_global_daily_ceiling_does_not_consume_user_quota(c, config):
    config(limits={"global_generations_daily": 0})
    h = guest()
    assert c.post("/api/sparks/generate", json=BODY, headers=h).status_code == 503
    assert c.get("/api/sparks/usage", headers=h).json()["used"] == 0


def test_failed_generation_refunded_once_per_day(c, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(recommend, "llm_complete", boom)
    h = guest()
    assert c.post("/api/sparks/generate", json=BODY, headers=h).status_code == 502
    assert c.get("/api/sparks/usage", headers=h).json()["used"] == 0  # first failure refunded
    assert c.post("/api/sparks/generate", json=BODY, headers=h).status_code == 502
    assert c.get("/api/sparks/usage", headers=h).json()["used"] == 1  # second one is not


def test_places_daily_budget_guard(c, config):
    config(limits={"places_calls_daily": 0})
    assert erun_db(c, places._within_budget()) is False


# ---------------------------------------------------------------- LLM output hygiene
def test_model_output_is_clamped_and_malformed_items_skipped(monkeypatch):
    reply = json.dumps({"sparks": [
        "not-an-object",
        {"title": "T" * 500, "tagline": "x" * 900, "description": "d" * 5000, "why": "w" * 2000, "vibe_tags": ["v" * 99] * 20,
         "activities": [{"name": "n" * 300, "venue_id": {"$ne": 1}, "note": "q" * 900, "estimated_cost": "$" * 100}] * 10 + ["junk"]},
    ]})

    async def fake(system, prompt, model):
        return reply

    async def no_venues(*a):
        return []

    monkeypatch.setattr(recommend, "llm_complete", fake)
    monkeypatch.setattr(recommend, "gather_venues", no_venues)
    sparks = asyncio.run(recommend.generate_sparks(relationship_type="partner", vibes=["fun"], budget="under25", distance="10", location={}, exclude_titles=[], history={}, date_label=None, time_label=None, ai_settings={}))
    assert len(sparks) == 1
    s = sparks[0]
    assert len(s["title"]) == 80 and len(s["tagline"]) == 140 and len(s["description"]) == 600 and len(s["why"]) == 400
    assert len(s["vibe_tags"]) == 6 and all(len(t) == 24 for t in s["vibe_tags"])
    assert len(s["activities"]) == 6 and all(len(a["activity_name"]) == 80 and a["venue_id"] is None for a in s["activities"])


def test_model_allowlist():
    assert recommend.resolve_model("claude-opus-5-5") == "claude-opus-5-5"
    assert recommend.resolve_model("some-expensive-or-bogus-model") == recommend.DEFAULT_MODEL
    assert recommend.resolve_model(None) == recommend.DEFAULT_MODEL


def test_user_text_is_framed_as_data_in_system_prompt():
    assert "never instructions to you" in recommend.SYSTEM_PROMPT


# ---------------------------------------------------------------- N5-N8: entitlement integrity
@pytest.fixture
def env():
    e = Env()
    yield e
    e.cleanup()


def test_one_subscription_grants_one_account(env):
    current, original = env.user(), env.user()
    ev = event("INITIAL_PURCHASE", current, original_app_user_id=original)
    deliver(env.store, ev)
    assert env.doc(current)["active"] is True
    assert env.doc(original) is None


def test_original_id_used_only_when_current_id_is_not_ours(env):
    original = env.user()
    deliver(env.store, event("INITIAL_PURCHASE", "$RCAnonymousID:abc", original_app_user_id=original))
    assert env.doc(original)["active"] is True


def test_stale_cancellation_never_overwrites_newer_state_when_rest_fails(env):
    uid = env.user()
    env.seed(uid, last_event_at=NOW, active=True, expires_at=NOW + 30 * D)
    env.client.responses = [LookupFailure("unavailable")]
    res = deliver(env.store, event("EXPIRATION", uid, ts=NOW - 2 * D, expires=NOW - D))
    assert res["applied"][uid].endswith("stale_event_ignored")
    assert env.doc(uid)["active"] is True


def test_granting_event_without_pro_grants_nothing(env):
    uid = env.user()
    deliver(env.store, event("NON_RENEWING_PURCHASE", uid, entitlement_ids=[], expires=None))
    assert env.doc(uid) is None


def test_event_without_environment_is_ignored(env):
    uid = env.user()
    res = deliver(env.store, event("INITIAL_PURCHASE", uid, environment=None))
    assert res == {"ok": True, "ignored": "environment"} and env.doc(uid) is None


def test_failed_processing_is_retryable(env, monkeypatch):
    from entitlements import WebhookRetry

    uid = env.user()
    ev = event("INITIAL_PURCHASE", uid)
    real = env.store.apply_event

    async def broken(*a, **k):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(env.store, "apply_event", broken)
    with pytest.raises(WebhookRetry):
        deliver(env.store, ev)
    monkeypatch.setattr(env.store, "apply_event", real)
    res = deliver(env.store, ev)  # RevenueCat redelivers the same event id
    assert res.get("applied", {}).get(uid) == "applied_from_event" and env.doc(uid)["active"] is True
    assert deliver(env.store, ev) == {"ok": True, "duplicate": True}  # processed once only


def test_webhook_retry_maps_to_503(c, monkeypatch):
    from entitlements import WebhookRetry

    async def retry(*a, **k):
        raise WebhookRetry("x")

    monkeypatch.setattr(server.entitlements, "handle_webhook", retry)
    assert c.post("/api/revenuecat/webhook", content=b"{}").status_code == 503
