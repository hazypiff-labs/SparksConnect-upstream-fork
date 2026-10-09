"""Phase A — subscription security & cost protection (audit B-1 / B-2 / B-3).

Limiter unit tests run against the real Mongo (unique keys per run); API tests use the local backend directly so the
client IP can be set via X-Real-IP (behind the ingress that header is proxy-controlled). Limits are lowered
temporarily through the admin API and always restored.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from limits import DEFAULT_LIMITS, LimitExceeded, Limiter, client_ip, limits_from  # noqa: E402

LOCAL = "http://localhost:8001/api"
PUBLIC = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vibe-finder-75.preview.emergentagent.com").rstrip("/") + "/api"
ADMIN = {"email": "admin@datespark.app", "password": "SparkAdmin2026!"}
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
BODY = {"relationship_type": "partner", "vibes": ["fun"], "budget": "25-50", "distance": "10", "location": AUSTIN}
CFG = {"free_spark_limit": 3, "limits": dict(DEFAULT_LIMITS)}


def run(c):
    return asyncio.run(c)


def fresh_limiter():
    return Limiter(AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]])


def ip():
    return f"198.51.100.{uuid.uuid4().int % 250}-{uuid.uuid4().hex[:6]}"


def guest():
    return f"guest-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------- limiter unit (real Mongo, unique keys)
def test_free_quota_is_atomic_under_concurrency():
    lim, g, addr = fresh_limiter(), guest(), ip()

    async def go():
        async def one():
            try:
                await lim.reserve_generation(ip=addr, owner_type="guest", owner_id=g, premium_claim=False, cfg=CFG)
                return "ok"
            except LimitExceeded as e:
                return e.scope

        return await asyncio.gather(*[one() for _ in range(40)])

    results = run(go())
    assert results.count("ok") == 3  # exactly the free allowance, no matter how many fire at once
    assert all(r in ("ok", "free_quota", "ip") for r in results)


def test_forged_premium_claim_is_capped_not_unlimited():
    lim, g, addr = fresh_limiter(), guest(), ip()
    cfg = {"free_spark_limit": 3, "limits": {**DEFAULT_LIMITS, "ip_hourly_cap": 100, "ip_daily_cap": 100, "premium_daily_cap": 4, "premium_monthly_cap": 10}}

    async def go():
        ok = 0
        for _ in range(8):
            try:
                await lim.reserve_generation(ip=addr, owner_type="guest", owner_id=g, premium_claim=True, cfg=cfg)
                ok += 1
            except LimitExceeded as e:
                assert e.status == 429 and e.scope == "premium_ceiling"
        return ok

    assert run(go()) == 4


def test_guest_id_rotation_is_capped_per_ip():
    lim, addr = fresh_limiter(), ip()
    cfg = {"free_spark_limit": 3, "limits": {**DEFAULT_LIMITS, "ip_hourly_cap": 100, "ip_daily_cap": 100, "guest_ids_per_ip_daily": 3}}

    async def go():
        scopes = []
        for _ in range(6):  # six brand-new guest ids from one network
            try:
                await lim.reserve_generation(ip=addr, owner_type="guest", owner_id=guest(), premium_claim=False, cfg=cfg)
                scopes.append("ok")
            except LimitExceeded as e:
                scopes.append(e.scope)
        return scopes

    assert run(go()) == ["ok", "ok", "ok", "guest_rotation", "guest_rotation", "guest_rotation"]


def test_known_guest_is_not_counted_as_rotation_and_users_are_exempt():
    lim, addr, g = fresh_limiter(), ip(), guest()
    cfg = {"free_spark_limit": 10, "limits": {**DEFAULT_LIMITS, "ip_hourly_cap": 100, "ip_daily_cap": 100, "guest_ids_per_ip_daily": 1}}

    async def go():
        await lim.reserve_generation(ip=addr, owner_type="guest", owner_id=g, premium_claim=False, cfg=cfg)
        await lim.reserve_generation(ip=addr, owner_type="guest", owner_id=g, premium_claim=False, cfg=cfg)  # same guest again: fine
        for _ in range(3):  # signed-in users on the same network are never treated as guest rotation
            await lim.reserve_generation(ip=addr, owner_type="user", owner_id=str(uuid.uuid4()), premium_claim=False, cfg=cfg)
        with pytest.raises(LimitExceeded) as e:
            await lim.reserve_generation(ip=addr, owner_type="guest", owner_id=guest(), premium_claim=False, cfg=cfg)
        assert e.value.scope == "guest_rotation"

    run(go())


def test_ip_caps_apply_before_identity_and_authenticated_user_limited_by_user_id():
    lim, addr, uid = fresh_limiter(), ip(), str(uuid.uuid4())
    cfg = {"free_spark_limit": 100, "limits": {**DEFAULT_LIMITS, "ip_hourly_cap": 2, "ip_daily_cap": 100}}

    async def go():
        await lim.reserve_generation(ip=addr, owner_type="user", owner_id=uid, premium_claim=True, cfg=cfg)
        await lim.reserve_generation(ip=addr, owner_type="user", owner_id=uid, premium_claim=True, cfg=cfg)
        with pytest.raises(LimitExceeded) as e:
            await lim.reserve_generation(ip=addr, owner_type="user", owner_id=uid, premium_claim=True, cfg=cfg)
        assert e.value.scope == "ip" and e.value.status == 429
        # same user from a new device/network: identity window still has room (device changes are fine)
        await lim.reserve_generation(ip=ip(), owner_type="user", owner_id=uid, premium_claim=True, cfg=cfg)

    run(go())


def test_release_returns_identity_units_but_keeps_ip_units():
    lim, addr, g = fresh_limiter(), ip(), guest()
    cfg = {"free_spark_limit": 1, "limits": {**DEFAULT_LIMITS, "ip_hourly_cap": 100, "ip_daily_cap": 100}}

    async def go():
        receipt = await lim.reserve_generation(ip=addr, owner_type="guest", owner_id=g, premium_claim=False, cfg=cfg)
        assert await lim.free_used("guest", g) == 1
        await lim.release(receipt)  # generation failed → give the free unit back
        assert await lim.free_used("guest", g) == 0
        await lim.reserve_generation(ip=addr, owner_type="guest", owner_id=g, premium_claim=False, cfg=cfg)  # allowed again
        ip_doc = await lim.db.rate_limits.find_one({"key": {"$regex": f"^ip:{addr}:hour:"}})
        assert ip_doc["count"] == 2  # IP attempts are never refunded

    run(go())


def test_expired_or_revoked_subscription_falls_back_to_free_quota():
    """The device SDK stops asserting Premium once RevenueCat expires/refunds/revokes the entitlement; the server then
    applies the free quota to the same identity — nothing server-side ever stored 'premium'."""
    lim, addr, uid = fresh_limiter(), ip(), str(uuid.uuid4())
    cfg = {"free_spark_limit": 1, "limits": {**DEFAULT_LIMITS, "ip_hourly_cap": 100, "ip_daily_cap": 100}}

    async def go():
        await lim.reserve_generation(ip=addr, owner_type="user", owner_id=uid, premium_claim=True, cfg=cfg)
        await lim.reserve_generation(ip=addr, owner_type="user", owner_id=uid, premium_claim=False, cfg=cfg)  # 1 free
        with pytest.raises(LimitExceeded) as e:
            await lim.reserve_generation(ip=addr, owner_type="user", owner_id=uid, premium_claim=False, cfg=cfg)
        assert e.value.status == 402 and e.value.scope == "free_quota"

    run(go())


def test_limiter_outage_fails_closed():
    class Broken:
        def __getattr__(self, _):
            raise RuntimeError("mongo down")

    lim = Limiter(Broken())
    with pytest.raises(LimitExceeded) as e:
        run(lim.reserve_generation(ip=ip(), owner_type="guest", owner_id=guest(), premium_claim=True, cfg=CFG))
    assert e.value.status == 429 and e.value.scope == "limiter_unavailable"


def test_client_ip_prefers_proxy_set_headers_and_ignores_forged_first_hop():
    class R:
        def __init__(self, headers, host="10.0.0.1"):
            self.headers, self.client = headers, type("C", (), {"host": host})()

    # platform chain: client, CDN, load balancer (2 trusted hops) — a client-prepended fake is ignored
    assert client_ip(R({"x-forwarded-for": "203.0.113.5, 172.69.1.1, 34.160.1.1"})) == "203.0.113.5"
    assert client_ip(R({"x-forwarded-for": "1.2.3.4, 203.0.113.5, 172.69.1.1, 34.160.1.1"})) == "203.0.113.5"
    assert client_ip(R({"x-forwarded-for": "203.0.113.9"})) == "203.0.113.9"  # direct / fewer hops than trusted
    assert client_ip(R({"cf-connecting-ip": "203.0.113.6", "x-forwarded-for": "9.9.9.9, 1.1.1.1, 2.2.2.2"})) == "203.0.113.6"
    assert client_ip(R({})) == "10.0.0.1"


def test_limits_config_sanitised():
    assert limits_from({}) == DEFAULT_LIMITS
    assert limits_from({"limits": {"ip_hourly_cap": 3, "bogus": 9, "premium_daily_cap": -1, "ip_daily_cap": "x"}})["ip_hourly_cap"] == 3
    assert limits_from({"limits": {"premium_daily_cap": -1}})["premium_daily_cap"] == DEFAULT_LIMITS["premium_daily_cap"]


# ---------------------------------------------------------------- API (local backend, controlled limits, restored)
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module")
def admin(s):
    r = s.post(f"{LOCAL}/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def tight_limits(s, admin):
    """Zero ceilings so every path is rejected BEFORE any Claude/Places call; restored afterwards."""
    before = s.get(f"{LOCAL}/admin/config", headers=admin).json()
    s.put(f"{LOCAL}/admin/config", headers=admin, json={"free_spark_limit": 0, "limits": {"premium_daily_cap": 0, "guest_ids_per_ip_daily": 0}})
    try:
        yield
    finally:
        r = s.put(f"{LOCAL}/admin/config", headers=admin, json={"free_spark_limit": before["free_spark_limit"], "limits": before["limits"]})
        assert r.json()["limits"] == before["limits"] and r.json()["free_spark_limit"] == before["free_spark_limit"]


def test_api_forged_premium_header_hits_server_ceiling(s, tight_limits):
    uid = f"guest-{uuid.uuid4().hex[:12]}"
    s.post(f"{LOCAL}/auth/signup", json={"email": f"pa-{uuid.uuid4().hex[:8]}@example.com", "password": "Passw0rd!xyz", "name": "P"})
    r = s.post(f"{LOCAL}/sparks/generate", headers={"X-Guest-ID": uid, "X-Premium": "1", "X-Forwarded-For": ip()}, json=BODY, timeout=10)
    # guest rotation cap (0) fires first for a brand-new guest; a known identity would hit the premium ceiling (0) — both 429, pre-LLM
    assert r.status_code == 429 and "Sign in" in r.json()["detail"]
    tok = s.post(f"{LOCAL}/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}).json()["access_token"]
    r = s.post(f"{LOCAL}/sparks/generate", headers={"Authorization": f"Bearer {tok}", "X-Premium": "1", "X-Forwarded-For": ip()}, json=BODY, timeout=10)
    assert r.status_code == 429 and "limit" in r.json()["detail"].lower() and "resets automatically" in r.json()["detail"]


def test_api_forged_subscription_mirror_grants_nothing(s, tight_limits):
    email = f"pa-{uuid.uuid4().hex[:8]}@example.com"
    tok = s.post(f"{LOCAL}/auth/signup", json={"email": email, "password": "Passw0rd!xyz", "name": "Forger"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}", "X-Forwarded-For": ip()}
    r = s.put(f"{LOCAL}/users/me/subscription", headers=h, json={"status": "premium", "provider": "revenuecat"})
    assert r.status_code == 200 and r.json()["subscription_status"] == "premium"  # accepted as self-report only
    me = s.get(f"{LOCAL}/auth/me", headers=h).json()
    assert me.get("subscription_status") == "premium"
    r = s.post(f"{LOCAL}/sparks/generate", headers=h, json=BODY, timeout=10)
    assert r.status_code == 402  # free quota (0) applies: the mirror bought no access


def test_api_guest_rotation_blocked_pre_llm(s, tight_limits):
    addr = ip()
    codes = [s.post(f"{LOCAL}/sparks/generate", headers={"X-Guest-ID": f"guest-{uuid.uuid4().hex[:12]}", "X-Forwarded-For": addr}, json=BODY, timeout=10).status_code for _ in range(3)]
    assert codes == [429, 429, 429]


def test_api_rate_limited_events_and_self_reported_metrics(s, admin):
    st = s.get(f"{LOCAL}/admin/stats", headers=admin).json()
    assert st["subscription_metrics_source"] == "self_reported" and st["rate_limited_requests"] >= 3
    cfg = s.get(f"{LOCAL}/admin/config", headers=admin).json()
    assert set(cfg["limits"]) == set(DEFAULT_LIMITS)
    pub = s.get(f"{PUBLIC}/config/public").json()
    assert "limits" not in pub  # not exposed publicly


def test_api_usage_endpoint_reflects_reservations(s):
    g = guest()
    u = s.get(f"{LOCAL}/sparks/usage", headers={"X-Guest-ID": g}).json()
    assert u == {"used": 0, "limit": u["limit"]} and u["limit"] >= 1


def test_api_live_legitimate_generation_still_works(s):
    """Default limits: a normal first-time guest generates successfully (Couple flow, surprise privacy untouched)."""
    g = guest()
    r = s.post(f"{PUBLIC}/sparks/generate", headers={"X-Guest-ID": g, "X-Premium": "1"}, json={**BODY, "surprise": True, "scheduled_at": "2099-01-01T01:00:00Z"}, timeout=170)
    assert r.status_code == 200, r.text
    sp = r.json()["sparks"][0]
    shared = s.get(f"{PUBLIC}/shared/{sp['id']}").json()
    assert shared["locked_for_recipient"] is True and shared["activities"] == []


def test_happy_path_response_shape_with_engine_mocked(monkeypatch):
    """Full endpoint pass (limits → generation → persistence → response) with only the AI engine stubbed, so a
    regression anywhere after the expensive call is caught without spending on Claude/Places."""
    import server
    from fastapi.testclient import TestClient

    async def fake_engine(**kwargs):
        return [{"title": f"T{uuid.uuid4().hex[:4]}", "emoji": "✨", "tagline": "a", "description": "d", "primary_vibe": "Fun", "vibe_tags": [], "estimated_cost": "$10", "estimated_duration": "1 hour", "why": "w",
                 "activities": [{"activity_name": "Coffee", "venue": None, "address": None, "lat": None, "lng": None, "rating": None, "hours": None, "start_time": "7:00 PM", "end_time": "8:00 PM", "estimated_cost": "$10", "external_url": None, "note": None, "verified": False}],
                 "location_label": "Austin", "distance_miles": None, "lat": None, "lng": None, "needs_verification": True, "travel_legs": [], "total_travel_minutes": None, "total_travel_miles": None,
                 "total_estimated_cost": 10.0, "per_person_cost": None, "priced_stops": 1, "unpriced_stops": 0, "complete": True, "routing_source": None}]

    monkeypatch.setattr(server, "generate_sparks", fake_engine)
    with TestClient(server.app) as c:
        g = guest()
        r = c.post("/api/sparks/generate", headers={"X-Guest-ID": g, "X-Forwarded-For": ip()}, json=BODY)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["sparks"]) == 1 and body["sparks"][0]["id"] and body["usage"]["used"] == 1 and body["usage"]["limit"] >= 1
        r2 = c.post("/api/sparks/generate", headers={"X-Guest-ID": g, "X-Premium": "1", "X-Forwarded-For": ip()}, json=BODY)
        assert r2.status_code == 200
        assert run(fresh_limiter().free_used("guest", g)) == 1  # the premium-claimed generation did not consume the free quota (display `used` counts all generations)
