"""Server-side RevenueCat entitlement verification (plan v3) — ALL RevenueCat HTTP is stubbed at
`RevenueCatClient._get`; this suite never contacts RevenueCat, never incurs charges and never needs a real secret.

Unit tests run the store against the real Mongo with unique user ids (cleaned up). API tests use the local backend:
the webhook secret is whatever dev-only value `backend/.env` holds (tests sign with it, nothing is printed), and the
`server_entitlements` flag is toggled ON only inside tests that restore it to OFF in `finally`.
"""
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import entitlements as ent  # noqa: E402
from entitlements import EntitlementStore, LookupFailure, RevenueCatClient, Settings, SignatureError, sign, verify_signature  # noqa: E402

LOCAL = os.environ["SPARKS_TEST_BASE_URL"] + "/api"
ADMIN = {"email": os.environ["SPARKS_TEST_ADMIN_EMAIL"], "password": os.environ["SPARKS_TEST_ADMIN_PASSWORD"]}
WEBHOOK_SECRET = os.environ.get("REVENUECAT_WEBHOOK_SECRET", "")
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
BODY = {"relationship_type": "partner", "vibes": ["fun"], "budget": "25-50", "distance": "10", "location": AUSTIN}

NOW = datetime.now(timezone.utc)
H = timedelta(hours=1)
D = timedelta(days=1)


LOOP = asyncio.new_event_loop()  # one loop for the module: Motor clients are loop-bound


def run(c):
    return LOOP.run_until_complete(c)


def mongo():
    return AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=LOOP)[os.environ["DB_NAME"]]


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def settings(**kw) -> Settings:
    base = dict(secret_key="stub-key", webhook_secret=WEBHOOK_SECRET or "unit-secret", webhook_auth="", project_id="proj_test", entitlement_id="", environment="SANDBOX")
    base.update(kw)
    return Settings(**base)


class StubClient(RevenueCatClient):
    """Scripted `_get`: queued (status, body) tuples or exceptions; records calls."""

    def __init__(self, st: Settings, *responses):
        super().__init__(st)
        self.responses, self.calls = list(responses), 0

    async def _get(self, url):
        self.calls += 1
        self.last_url = url
        r = self.responses.pop(0) if self.responses else (200, {"items": []})
        if isinstance(r, Exception):
            raise r
        return r


def active_body(expires: datetime | None = NOW + 30 * D, eid="entl_pro"):
    return (200, {"object": "list", "items": [{"object": "customer.active_entitlement", "entitlement_id": eid, "expires_at": ms(expires) if expires else None}]})


EMPTY = (200, {"object": "list", "items": []})


class Env:
    """Fresh DB handle + a store with a stub client + scratch users; cleans up what it created."""

    def __init__(self, *responses, st: Settings | None = None):
        self.db = mongo()
        self.settings = st or settings()
        self.client = StubClient(self.settings, *responses)
        self.store = EntitlementStore(self.db, self.settings, self.client)
        self.users: list[str] = []

    def user(self, deleted=False, status="free") -> str:
        uid = str(uuid.uuid4())
        run(self.db.users.insert_one({"id": uid, "name": "Ent", "email": f"ent-{uid[:12]}@example.com", "password_hash": "x", "role": "user", "subscription_status": status, "created_at": NOW, "deleted_at": NOW if deleted else None}))
        self.users.append(uid)
        return uid

    def doc(self, uid):
        return run(self.db.entitlements.find_one({"user_id": uid}, {"_id": 0}))

    def seed(self, uid, **fields):
        base = {"user_id": uid, "entitlement": "pro", "active": True, "expires_at": NOW + 10 * D, "source": "webhook", "checked_at": NOW, "updated_at": NOW}
        base.update(fields)
        run(self.db.entitlements.update_one({"user_id": uid}, {"$set": base}, upsert=True))

    def cleanup(self):
        if self.users:
            run(self.db.users.delete_many({"id": {"$in": self.users}}))
            run(self.db.entitlements.delete_many({"user_id": {"$in": self.users}}))


@pytest.fixture
def env():
    e = Env()
    yield e
    e.cleanup()


def event(etype, uid, *, eid=None, expires: datetime | None = NOW + 30 * D, ts: datetime = NOW, environment="SANDBOX", **extra):
    ev = {"id": eid or str(uuid.uuid4()), "type": etype, "app_user_id": uid, "original_app_user_id": uid, "environment": environment, "event_timestamp_ms": ms(ts), "entitlement_ids": ["pro"], "store": "APP_STORE", "product_id": "premium_monthly"}
    if expires is not None:
        ev["expiration_at_ms"] = ms(expires)
    ev.update(extra)
    return ev


def deliver(store: EntitlementStore, ev: dict, secret: str | None = None, ts: int | None = None, authorization=None):
    raw = json.dumps({"api_version": "1.0", "event": ev}).encode()
    header = sign(raw, secret or store.settings.webhook_secret, ts or int(time.time()))
    return run(store.handle_webhook(raw, header, authorization))


# ---------------------------------------------------------------- signature
def test_signature_valid_invalid_missing_malformed_stale():
    raw, secret, t = b'{"event":{"id":"1"}}', "s3cret", int(time.time())
    verify_signature(raw, sign(raw, secret, t), secret)  # valid
    with pytest.raises(SignatureError):
        verify_signature(raw + b" ", sign(raw, secret, t), secret)  # body altered
    with pytest.raises(SignatureError):
        verify_signature(raw, sign(raw, "other", t), secret)  # wrong secret
    with pytest.raises(SignatureError):
        verify_signature(raw, None, secret)  # missing
    with pytest.raises(SignatureError):
        verify_signature(raw, "garbage", secret)  # malformed
    with pytest.raises(SignatureError):
        verify_signature(raw, sign(raw, secret, t - 600), secret)  # stale (replay)
    with pytest.raises(SignatureError):
        verify_signature(raw, sign(raw, secret, t + 600), secret)  # future
    with pytest.raises(SignatureError):
        verify_signature(raw, sign(raw, secret, t), "")  # signing not configured → never accepted


def test_webhook_rejects_bad_signature_and_optional_auth_header(env):
    uid = env.user()
    with pytest.raises(SignatureError):
        deliver(env.store, event("INITIAL_PURCHASE", uid), secret="wrong")
    assert env.doc(uid) is None
    strict = Env(st=settings(webhook_auth="Bearer hook-token"))
    try:
        with pytest.raises(SignatureError):
            deliver(strict.store, event("INITIAL_PURCHASE", uid))
        assert deliver(strict.store, event("INITIAL_PURCHASE", uid), authorization="Bearer hook-token")["ok"]
    finally:
        run(strict.db.entitlements.delete_many({"user_id": uid}))


# ---------------------------------------------------------------- idempotency / ordering / environment
def test_duplicate_event_acknowledged_once(env):
    uid, ev = env.user(), event("INITIAL_PURCHASE", env.user())
    ev["app_user_id"] = ev["original_app_user_id"] = uid
    first = deliver(env.store, ev)
    assert first["applied"][uid] == "applied_from_event"
    run(env.db.entitlements.update_one({"user_id": uid}, {"$set": {"active": False}}))
    second = deliver(env.store, ev)
    assert second == {"ok": True, "duplicate": True}
    assert env.doc(uid)["active"] is False  # not re-applied


def test_out_of_order_events_converge(env):
    uid = env.user()
    # EXPIRATION (newest, REST confirms empty) arrives first, then a late RENEWAL from the past.
    env.client.responses = [EMPTY]
    deliver(env.store, event("EXPIRATION", uid, expires=NOW - H, ts=NOW))
    assert env.doc(uid)["active"] is False
    res = deliver(env.store, event("RENEWAL", uid, expires=NOW - H, ts=NOW - 2 * D))
    assert res["applied"][uid] == "stale_event_ignored"
    assert env.doc(uid)["active"] is False
    # A genuinely newer RENEWAL re-activates.
    deliver(env.store, event("RENEWAL", uid, expires=NOW + 30 * D, ts=NOW + H))
    assert run(env.store.resolve(uid)) == (True, "verified")


def test_wrong_environment_is_recorded_but_not_applied(env):
    uid = env.user()
    res = deliver(env.store, event("INITIAL_PURCHASE", uid, environment="PRODUCTION"))
    assert res == {"ok": True, "ignored": "environment"}
    assert env.doc(uid) is None
    assert run(env.store.resolve(uid))[0] is False


def test_unknown_and_deleted_users_get_nothing(env):
    ghost, gone = str(uuid.uuid4()), env.user(deleted=True)
    r1 = deliver(env.store, event("INITIAL_PURCHASE", ghost))
    r2 = deliver(env.store, event("INITIAL_PURCHASE", gone))
    assert r1["applied"][ghost] == "unknown_user" and r2["applied"][gone] == "unknown_user"
    assert env.doc(ghost) is None and env.doc(gone) is None
    assert run(env.store.resolve(ghost)) == (False, "unknown_user")
    assert run(env.store.resolve(gone)) == (False, "unknown_user")
    stored = run(env.db.webhook_events.find_one({"app_user_id": ghost}, {"_id": 0}))
    assert stored and stored["status"] == "processed"  # audited, never granted


# ---------------------------------------------------------------- event semantics
def test_initial_purchase_grants_until_expiry(env):
    uid = env.user()
    deliver(env.store, event("INITIAL_PURCHASE", uid, expires=NOW + 30 * D))
    d = env.doc(uid)
    assert d["active"] and d["source"] == "webhook" and d["last_event_type"] == "INITIAL_PURCHASE"
    assert run(env.store.resolve(uid)) == (True, "verified")
    assert env.client.calls == 0  # fresh webhook state → no lookup needed


def test_cancellation_keeps_access_until_expiry_then_ends(env):
    uid = env.user()
    env.client.responses = [active_body(NOW + 5 * D)]
    deliver(env.store, event("CANCELLATION", uid, expires=NOW + 5 * D, cancel_reason="UNSUBSCRIBE"))
    assert run(env.store.resolve(uid))[0] is True
    # time passes: stored expiry in the past → lookup → RevenueCat has nothing active
    env.seed(uid, expires_at=NOW - H)
    env.client.responses = [EMPTY]
    assert run(env.store.resolve(uid)) == (False, "inactive")


def test_refund_revokes_immediately(env):
    uid = env.user()
    env.seed(uid)
    env.client.responses = [EMPTY]  # RevenueCat truth after refund
    res = deliver(env.store, event("CANCELLATION", uid, expires=NOW + 20 * D, cancel_reason="CUSTOMER_SUPPORT"))
    assert res["applied"][uid] == "resynced"
    assert run(env.store.resolve(uid)) == (False, "inactive")


def test_refund_without_rest_uses_event_semantics(env):
    uid = env.user()
    env.seed(uid)
    env.client.responses = [(503, None)]
    res = deliver(env.store, event("CANCELLATION", uid, expires=NOW + 20 * D, cancel_reason="CUSTOMER_SUPPORT"))
    assert res["applied"][uid] == "lookup_failed:unavailable:applied_from_event"
    d = env.doc(uid)
    assert d["active"] is False and d.get("refunded_at")


def test_expiration_event_ends_access(env):
    uid = env.user()
    env.seed(uid)
    env.client.responses = [EMPTY]
    deliver(env.store, event("EXPIRATION", uid, expires=NOW - H, expiration_reason="UNSUBSCRIBE"))
    assert run(env.store.resolve(uid)) == (False, "inactive")


def test_billing_issue_grace_period_from_store(env):
    uid = env.user()
    env.client.responses = [(503, None)]  # no REST → event semantics
    deliver(env.store, event("BILLING_ISSUE", uid, expires=NOW - H, grace_period_expiration_at_ms=ms(NOW + 3 * D)))
    d = env.doc(uid)
    assert d["active"] and d["grace_period_expires_at"]
    assert EntitlementStore.is_current(d, NOW) is True
    assert EntitlementStore.is_current(d, NOW + 4 * D) is False


def test_transfer_moves_access(env):
    loser, gainer = env.user(), env.user()
    env.seed(loser)
    env.client.responses = [EMPTY, active_body()]  # loser re-fetched → empty; gainer → active
    ev = event("TRANSFER", gainer, expires=None, transferred_from=[loser], transferred_to=[gainer])
    ev.pop("entitlement_ids")
    res = deliver(env.store, ev)
    assert res["applied"] == {loser: "resynced", gainer: "resynced"}
    assert run(env.store.resolve(loser))[0] is False
    assert run(env.store.resolve(gainer))[0] is True


def test_transfer_without_rest_revokes_loser_and_grants_nothing(env):
    loser, gainer = env.user(), env.user()
    env.seed(loser)
    env.client.responses = [httpx.ReadTimeout("t"), httpx.ReadTimeout("t")]
    ev = event("TRANSFER", gainer, expires=None, transferred_from=[loser], transferred_to=[gainer])
    res = deliver(env.store, ev)
    assert res["applied"][loser] == "lookup_failed:timeout:revoked"
    assert res["applied"][gainer] == "lookup_failed:timeout:not_applicable"
    assert env.doc(loser)["active"] is False and env.doc(gainer) is None


def test_event_for_other_entitlement_is_ignored(env):
    uid = env.user()
    res = deliver(env.store, event("INITIAL_PURCHASE", uid, entitlement_ids=["other_tier"]))
    assert res["applied"][uid] == "not_applicable" and env.doc(uid) is None


# ---------------------------------------------------------------- lookups / fail-closed / grace
def test_first_lookup_success_and_404_and_pinned_entitlement(env):
    a, b, c = env.user(), env.user(), env.user()
    env.client.responses = [active_body(), (404, {"type": "resource_missing"})]
    assert run(env.store.resolve(a)) == (True, "verified")
    assert env.doc(a)["source"] == "lookup" and env.doc(a)["lookup_status"] == "ok"
    assert run(env.store.resolve(b)) == (False, "inactive")
    assert env.doc(b)["lookup_status"] == "not_found"
    assert env.client.last_url.endswith(f"/projects/proj_test/customers/{b}/active_entitlements")
    pinned = Env(active_body(eid="entl_other"), st=settings(entitlement_id="entl_pro"))
    try:
        pinned.users.append(c)
        assert run(pinned.store.resolve(c)) == (False, "inactive")
    finally:
        pinned.cleanup()


def test_auth_error_fails_closed_without_grace(env):
    fresh, expired = env.user(), env.user()
    env.client.responses = [(403, {"message": "forbidden"}), (401, None)]
    assert run(env.store.resolve(fresh)) == (False, "no_evidence:auth")
    assert env.doc(fresh) is None
    env.seed(expired, expires_at=NOW - H, checked_at=NOW - 2 * D)  # recently expired, last known active
    assert run(env.store.resolve(expired)) == (False, "inactive")  # auth errors are not outages → no grace


def test_transient_failures_grace_only_for_recently_verified_active(env):
    recent, old, never, inactive = env.user(), env.user(), env.user(), env.user()
    env.seed(recent, expires_at=NOW - 10 * H)  # expired 10 h ago, last verified active
    env.seed(old, expires_at=NOW - 80 * H)  # expired > 72 h ago
    env.seed(inactive, active=False, expires_at=NOW - H)  # last known inactive
    env.client.responses = [(429, None), (503, None), httpx.ConnectTimeout("x"), (502, None)]
    assert run(env.store.resolve(recent)) == (True, "grace:rate_limited")
    assert env.doc(recent).get("last_grace_at")
    assert run(env.store.resolve(old)) == (False, "inactive")
    assert run(env.store.resolve(never)) == (False, "no_evidence:timeout")
    assert env.doc(never) is None
    assert run(env.store.resolve(inactive)) == (False, "inactive")


def test_stale_doc_triggers_lookup_fresh_doc_does_not(env):
    stale, fresh = env.user(), env.user()
    env.seed(stale, checked_at=NOW - 25 * H)
    env.seed(fresh, checked_at=NOW - H)
    env.client.responses = [EMPTY]
    assert run(env.store.resolve(stale)) == (False, "inactive")  # REST truth overrides the stale doc
    assert env.client.calls == 1
    assert run(env.store.resolve(fresh)) == (True, "verified")
    assert env.client.calls == 1  # bounded: no lookup for fresh evidence


def test_stale_verified_state_with_lookup_outage_is_still_honoured_until_expiry(env):
    uid = env.user()
    env.seed(uid, checked_at=NOW - 30 * H, expires_at=NOW + 2 * D)
    env.client.responses = [(503, None)]
    assert run(env.store.resolve(uid)) == (True, "verified")  # stored evidence still valid, no grace needed


def test_lookup_error_mapping_and_timeout(env):
    st = settings()
    for resp, kind in (((401, None), "auth"), ((403, None), "auth"), ((404, None), "not_found"), ((429, None), "rate_limited"), ((500, None), "unavailable"), ((200, "not-a-dict"), "unavailable"), (httpx.ReadTimeout("t"), "timeout"), (httpx.ConnectError("c"), "unavailable")):
        c = StubClient(st, resp)
        with pytest.raises(LookupFailure) as ei:
            run(c.active_entitlements("u"))
        assert ei.value.kind == kind
    with pytest.raises(LookupFailure) as ei:
        run(RevenueCatClient(settings(secret_key="")).active_entitlements("u"))
    assert ei.value.kind == "unconfigured"
    assert ent.LOOKUP_TIMEOUT_SECONDS <= 10


def test_resolve_store_outage_never_grants(env):
    uid = env.user()

    class Broken(EntitlementStore):
        async def _user_exists(self, user_id):
            raise RuntimeError("mongo down")

    broken = Broken(env.db, env.settings, env.client)
    with pytest.raises(RuntimeError):
        run(broken.resolve(uid))  # server.verified_entitlement catches this and returns False


# ---------------------------------------------------------------- backfill
def test_backfill_aborts_on_auth_and_persists_nothing(env):
    uid = env.user(status="premium")
    env.client.responses = [(403, None)]
    rep = run(env.store.backfill(dry_run=False, limit=5000))
    assert rep["aborted"] == "auth_error"
    assert env.doc(uid) is None


def test_backfill_dry_run_reports_mismatches_without_persisting(env):
    uid = env.user(status="premium")  # self-reported premium, RevenueCat never saw this id
    env.client.responses = [(404, None)]
    rep = run(env.store.backfill(dry_run=True, user_ids=[uid]))
    assert rep["checked"] == 1 and rep["never_seen"] == 1 and rep["mismatches"] == [{"user_id": uid, "self_reported": "premium", "verified": "never_seen"}]
    assert env.doc(uid) is None
    # live run: rate-limited once (backs off, resumes) then active → persisted as verified, exact id attribution
    env.client.responses = [(429, None), active_body()]
    rep = run(env.store.backfill(dry_run=False, user_ids=[uid]))
    assert rep["verified_active"] == 1 and rep["mismatches"] == [] and env.client.calls == 3
    assert env.doc(uid)["active"] is True and env.doc(uid)["source"] == "lookup"
    # deleted users are never candidates
    gone = env.user(deleted=True, status="premium")
    assert run(env.store.backfill(dry_run=True, user_ids=[gone]))["checked"] == 0


def test_backfill_unconfigured_aborts():
    st = settings(secret_key="")
    rep = run(EntitlementStore(mongo(), st, StubClient(st)).backfill())
    assert rep["aborted"] == "unconfigured" and rep["checked"] == 0


# ---------------------------------------------------------------- API (local backend; flag toggled only inside, restored)
def admin_headers():
    tok = requests.post(f"{LOCAL}/auth/login", json=ADMIN, timeout=20).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def put_cfg(h, body):
    r = requests.put(f"{LOCAL}/admin/config", headers=h, json=body, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def signup():
    email = f"ent-api-{uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{LOCAL}/auth/signup", json={"name": "Ent", "email": email, "password": "Passw0rd!xyz"}, timeout=20)
    r.raise_for_status()
    return r.json()["user"]["id"], {"Authorization": f"Bearer {r.json()['access_token']}", "X-Real-IP": f"203.0.113.{uuid.uuid4().int % 250}"}


def post_webhook(ev, secret=WEBHOOK_SECRET, ts=None, raw_override=None):
    raw = raw_override or json.dumps({"api_version": "1.0", "event": ev}).encode()
    return requests.post(f"{LOCAL}/revenuecat/webhook", data=raw, headers={"Content-Type": "application/json", "X-RevenueCat-Webhook-Signature": sign(raw, secret, ts or int(time.time()))}, timeout=20)


def test_api_flag_default_off_and_public_config():
    cfg = requests.get(f"{LOCAL}/config/public", timeout=20).json()
    assert cfg["features"].get("server_entitlements") is False
    h = admin_headers()
    stats = requests.get(f"{LOCAL}/admin/stats", headers=h, timeout=20).json()
    assert stats["server_entitlements"]["flag"] is False
    assert set(stats["server_entitlements"]) >= {"lookups_configured", "webhook_configured", "environment"}
    assert "verified_premium_users" in stats and "last_webhook_at" in stats
    assert not any(k.lower().endswith(("secret", "key")) and isinstance(v, str) and len(v) > 8 for k, v in stats["server_entitlements"].items())


@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set in backend/.env")
def test_api_webhook_signature_paths():
    uid, _ = signup()
    ev = event("INITIAL_PURCHASE", uid)
    assert requests.post(f"{LOCAL}/revenuecat/webhook", json={"event": ev}, timeout=20).status_code == 401  # unsigned
    assert post_webhook(ev, secret="forged").status_code == 401
    assert post_webhook(ev, ts=int(time.time()) - 900).status_code == 401  # replayed/stale
    ok = post_webhook(ev)
    assert ok.status_code == 200 and ok.json()["applied"][uid] == "applied_from_event"
    dup = post_webhook(ev)
    assert dup.status_code == 200 and dup.json() == {"ok": True, "duplicate": True}
    check = requests.get(f"{LOCAL}/admin/entitlement-check", params={"user_id": uid}, headers=admin_headers(), timeout=20).json()
    assert check["verified_active_now"] is True and check["self_reported_status"] == "free"
    assert requests.get(f"{LOCAL}/admin/entitlement-check", params={"user_id": uid}, timeout=20).status_code == 401


@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set in backend/.env")
def test_api_flag_off_vs_on_forged_header_expiry_and_rollback():
    """End-to-end with zero LLM cost: free quota 0 → 402 for everyone except server-verified users, who hit the
    bounded Premium lane (premium_daily_cap 0 → 429 'resets automatically')."""
    h = admin_headers()
    before = requests.get(f"{LOCAL}/admin/config", headers=h, timeout=20).json()
    uid, uh = signup()
    try:
        put_cfg(h, {"free_spark_limit": 0, "limits": {"premium_daily_cap": 0}, "features": {"server_entitlements": False}})
        # Webhook state exists, flag OFF → Phase A: 402, forged header irrelevant
        assert post_webhook(event("INITIAL_PURCHASE", uid)).status_code == 200
        requests.put(f"{LOCAL}/users/me/subscription", headers=uh, json={"status": "premium", "provider": "revenuecat"}, timeout=20)
        for extra in ({}, {"X-Premium": "1"}):
            r = requests.post(f"{LOCAL}/sparks/generate", json=BODY, headers={**uh, **extra}, timeout=30)
            assert r.status_code == 402, r.text
        # Flag ON → verified user reaches the Premium lane (429 at the zero cap), still independent of the header
        put_cfg(h, {"features": {"server_entitlements": True}})
        for extra in ({}, {"X-Premium": "1"}):
            r = requests.post(f"{LOCAL}/sparks/generate", json=BODY, headers={**uh, **extra}, timeout=30)
            assert r.status_code == 429 and "resets automatically" in r.json()["detail"], r.text
        # Unverified user with forged header + forged mirror → still 402 while ON
        _, fh = signup()
        requests.put(f"{LOCAL}/users/me/subscription", headers=fh, json={"status": "premium", "provider": "revenuecat"}, timeout=20)
        r = requests.post(f"{LOCAL}/sparks/generate", json=BODY, headers={**fh, "X-Premium": "1"}, timeout=30)
        assert r.status_code == 402, r.text
        # Expiration webhook (lookups unconfigured in dev → event semantics) → back to 402
        assert post_webhook(event("EXPIRATION", uid, expires=NOW - H, ts=NOW + H)).status_code == 200
        r = requests.post(f"{LOCAL}/sparks/generate", json=BODY, headers=uh, timeout=30)
        assert r.status_code == 402, r.text
        # Rollback: flag OFF restores Phase A instantly
        put_cfg(h, {"features": {"server_entitlements": False}})
        assert post_webhook(event("RENEWAL", uid, ts=NOW + 2 * H)).status_code == 200
        r = requests.post(f"{LOCAL}/sparks/generate", json=BODY, headers=uh, timeout=30)
        assert r.status_code == 402, r.text
    finally:
        after = put_cfg(h, {"free_spark_limit": before["free_spark_limit"], "limits": {"premium_daily_cap": before["limits"]["premium_daily_cap"]}, "features": {"server_entitlements": False}})
        assert after["features"]["server_entitlements"] is False
        assert after["free_spark_limit"] == before["free_spark_limit"]


def test_api_admin_reverify_and_backfill_without_key_are_safe():
    h = admin_headers()
    uid, _ = signup()
    r = requests.post(f"{LOCAL}/admin/entitlement-check/{uid}/reverify", headers=h, timeout=20)
    assert r.status_code == 502 and "unconfigured" in r.json()["detail"]  # no key in dev → nothing granted
    assert requests.post(f"{LOCAL}/admin/entitlement-check/{uuid.uuid4()}/reverify", headers=h, timeout=20).status_code == 404
    rep = requests.post(f"{LOCAL}/admin/entitlements/backfill", headers=h, json={"dry_run": True}, timeout=20).json()
    assert rep["dry_run"] is True and rep["aborted"] == "unconfigured" and rep["checked"] == 0
    rep = requests.post(f"{LOCAL}/admin/entitlements/backfill", headers=h, timeout=20).json()
    assert rep["dry_run"] is True  # default is a dry run
    assert requests.post(f"{LOCAL}/admin/entitlements/backfill", timeout=20).status_code == 401
