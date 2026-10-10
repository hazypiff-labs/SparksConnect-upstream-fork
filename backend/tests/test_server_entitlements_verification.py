"""Independent API-level verification for server-side RevenueCat entitlements.
Tests run against the locally running backend (http://localhost:8001/api) with the
dev webhook secret read from backend/.env for signing. Never prints the secret.
Leaves `features.server_entitlements` OFF and admin config restored at the end.
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from entitlements import sign  # noqa: E402

LOCAL = "http://localhost:8001/api"
ADMIN = {"email": "admin@datespark.app", "password": "SparkAdmin2026!"}
WEBHOOK_SECRET = os.environ.get("REVENUECAT_WEBHOOK_SECRET", "")
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
BODY = {"relationship_type": "partner", "vibes": ["fun"], "budget": "25-50", "distance": "10", "location": AUSTIN}

NOW = datetime.now(timezone.utc)
H = timedelta(hours=1)
D = timedelta(days=1)


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def admin_headers():
    r = requests.post(f"{LOCAL}/auth/login", json=ADMIN, timeout=20)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def unique_ip():
    return f"203.0.113.{uuid.uuid4().int % 250 + 1}"


def signup():
    email = f"ent-ver-{uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(
        f"{LOCAL}/auth/signup",
        json={"name": "Ver", "email": email, "password": "Passw0rd!xyz"},
        timeout=20,
        headers={"X-Real-IP": unique_ip()},
    )
    r.raise_for_status()
    data = r.json()
    return data["user"]["id"], {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Real-IP": unique_ip(),
    }


def put_cfg(h, body):
    r = requests.put(f"{LOCAL}/admin/config", headers=h, json=body, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def event(etype, uid, *, eid=None, expires=None, ts=None, environment="SANDBOX", **extra):
    expires = expires if expires is not None else (NOW + 30 * D)
    ts = ts or NOW
    ev = {
        "id": eid or str(uuid.uuid4()),
        "type": etype,
        "app_user_id": uid,
        "original_app_user_id": uid,
        "environment": environment,
        "event_timestamp_ms": ms(ts),
        "entitlement_ids": ["pro"],
        "store": "APP_STORE",
        "product_id": "premium_monthly",
    }
    if expires is not None:
        ev["expiration_at_ms"] = ms(expires)
    ev.update(extra)
    return ev


def post_webhook(ev, secret=None, ts=None, signed=True):
    raw = json.dumps({"api_version": "1.0", "event": ev}).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-RevenueCat-Webhook-Signature"] = sign(
            raw, secret if secret is not None else WEBHOOK_SECRET, ts or int(time.time())
        )
    return requests.post(f"{LOCAL}/revenuecat/webhook", data=raw, headers=headers, timeout=20)


# ---------- 1. Public config
def test_public_config_server_entitlements_off():
    r = requests.get(f"{LOCAL}/config/public", timeout=20)
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["features"].get("server_entitlements") is False
    # regression spot check
    assert cfg["features"].get("real_routing") is False


# ---------- 2. Webhook signature paths
@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_webhook_unsigned_401():
    ev = event("INITIAL_PURCHASE", str(uuid.uuid4()))
    r = post_webhook(ev, signed=False)
    assert r.status_code == 401, r.text


@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_webhook_wrong_secret_401():
    ev = event("INITIAL_PURCHASE", str(uuid.uuid4()))
    r = post_webhook(ev, secret="forged-wrong-secret-xyz")
    assert r.status_code == 401, r.text


@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_webhook_stale_timestamp_401():
    ev = event("INITIAL_PURCHASE", str(uuid.uuid4()))
    r = post_webhook(ev, ts=int(time.time()) - 15 * 60)
    assert r.status_code == 401, r.text


@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_webhook_valid_signature_applies_to_known_user():
    uid, _ = signup()
    ev = event("INITIAL_PURCHASE", uid)
    r = post_webhook(ev)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"][uid] == "applied_from_event"


@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_webhook_duplicate_event_returns_duplicate_true():
    uid, _ = signup()
    ev = event("INITIAL_PURCHASE", uid)
    r1 = post_webhook(ev)
    assert r1.status_code == 200
    r2 = post_webhook(ev)
    assert r2.status_code == 200
    assert r2.json() == {"ok": True, "duplicate": True}


@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_webhook_production_environment_in_sandbox_dev_ignored():
    uid, _ = signup()
    ev = event("INITIAL_PURCHASE", uid, environment="PRODUCTION")
    r = post_webhook(ev)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "ignored": "environment"}


@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_webhook_unknown_user_id_marked_unknown_user():
    ghost = str(uuid.uuid4())
    ev = event("INITIAL_PURCHASE", ghost)
    r = post_webhook(ev)
    assert r.status_code == 200, r.text
    assert r.json()["applied"][ghost] == "unknown_user"


# ---------- 3. Admin endpoints
@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_admin_entitlement_check_after_initial_purchase():
    uid, _ = signup()
    r = post_webhook(event("INITIAL_PURCHASE", uid))
    assert r.status_code == 200
    h = admin_headers()
    check = requests.get(
        f"{LOCAL}/admin/entitlement-check", params={"user_id": uid}, headers=h, timeout=20
    )
    assert check.status_code == 200, check.text
    data = check.json()
    assert data["verified_active_now"] is True
    assert data["self_reported_status"] == "free"
    cfg = data["config"]
    # config must contain only booleans/strings like environment, no secret values
    for k, v in cfg.items():
        if isinstance(v, str):
            # Only expected string is environment
            assert k == "environment" or len(v) <= 32, f"suspicious config value for {k}"
        else:
            assert isinstance(v, bool), f"unexpected type for {k}: {type(v)}"
    # unauthenticated
    r_un = requests.get(f"{LOCAL}/admin/entitlement-check", params={"user_id": uid}, timeout=20)
    assert r_un.status_code == 401


def test_admin_reverify_unconfigured_502_and_unknown_404():
    h = admin_headers()
    uid, _ = signup()
    r = requests.post(f"{LOCAL}/admin/entitlement-check/{uid}/reverify", headers=h, timeout=20)
    assert r.status_code == 502
    assert "unconfigured" in r.json()["detail"].lower()
    r404 = requests.post(
        f"{LOCAL}/admin/entitlement-check/{uuid.uuid4()}/reverify", headers=h, timeout=20
    )
    assert r404.status_code == 404


def test_admin_backfill_dry_run_unconfigured():
    h = admin_headers()
    r = requests.post(
        f"{LOCAL}/admin/entitlements/backfill", headers=h, json={"dry_run": True}, timeout=20
    )
    assert r.status_code == 200
    data = r.json()
    assert data["dry_run"] is True
    assert data["aborted"] == "unconfigured"
    assert data["checked"] == 0
    # no body → defaults to dry run
    r2 = requests.post(f"{LOCAL}/admin/entitlements/backfill", headers=h, timeout=20)
    assert r2.status_code == 200
    assert r2.json()["dry_run"] is True
    # unauth
    r_un = requests.post(f"{LOCAL}/admin/entitlements/backfill", timeout=20)
    assert r_un.status_code == 401


def test_admin_stats_shape_and_flag_off():
    h = admin_headers()
    r = requests.get(f"{LOCAL}/admin/stats", headers=h, timeout=20)
    assert r.status_code == 200
    s = r.json()
    for key in ("verified_premium_users", "last_webhook_at", "webhooks_rejected_30d", "grace_grants_30d"):
        assert key in s, f"missing {key} in stats"
    assert s["server_entitlements"]["flag"] is False


# ---------- 4. End-to-end lane test with zero LLM cost
@pytest.mark.skipif(not WEBHOOK_SECRET, reason="dev webhook secret not set")
def test_end_to_end_lane_zero_llm_cost():
    h = admin_headers()
    before = requests.get(f"{LOCAL}/admin/config", headers=h, timeout=20).json()
    saved_free_limit = before["free_spark_limit"]
    saved_premium_cap = before["limits"]["premium_daily_cap"]
    try:
        # Set zero-cost config
        put_cfg(h, {
            "free_spark_limit": 0,
            "limits": {"premium_daily_cap": 0},
            "features": {"server_entitlements": False},
        })
        uid, uh = signup()
        # valid INITIAL_PURCHASE webhook
        r = post_webhook(event("INITIAL_PURCHASE", uid))
        assert r.status_code == 200
        # forged self-reported mirror
        requests.put(
            f"{LOCAL}/users/me/subscription",
            headers=uh,
            json={"status": "premium", "provider": "revenuecat"},
            timeout=20,
        )
        # flag OFF: generate must be 402 with and without X-Premium
        for extra in ({}, {"X-Premium": "1"}):
            r = requests.post(
                f"{LOCAL}/sparks/generate", json=BODY, headers={**uh, **extra}, timeout=30
            )
            assert r.status_code == 402, f"flag OFF → expected 402, got {r.status_code}: {r.text}"

        # flag ON: verified user hits premium lane with cap 0 → 429
        put_cfg(h, {"features": {"server_entitlements": True}})
        for extra in ({}, {"X-Premium": "1"}):
            r = requests.post(
                f"{LOCAL}/sparks/generate", json=BODY, headers={**uh, **extra}, timeout=30
            )
            assert r.status_code == 429, f"flag ON verified → expected 429, got {r.status_code}: {r.text}"
            assert "resets automatically" in r.json().get("detail", ""), r.text

        # second user V with X-Premium:1 and forged mirror but no webhook → still 402
        _, vh = signup()
        requests.put(
            f"{LOCAL}/users/me/subscription",
            headers=vh,
            json={"status": "premium", "provider": "revenuecat"},
            timeout=20,
        )
        r = requests.post(
            f"{LOCAL}/sparks/generate", json=BODY, headers={**vh, "X-Premium": "1"}, timeout=30
        )
        assert r.status_code == 402, f"unverified premium forged → expected 402, got {r.status_code}: {r.text}"

        # EXPIRATION webhook for U (expiration in the past, event_ts after INITIAL_PURCHASE)
        r = post_webhook(
            event("EXPIRATION", uid, expires=NOW - H, ts=NOW + H, expiration_reason="UNSUBSCRIBE")
        )
        assert r.status_code == 200
        r = requests.post(f"{LOCAL}/sparks/generate", json=BODY, headers=uh, timeout=30)
        assert r.status_code == 402, f"after EXPIRATION expected 402, got {r.status_code}: {r.text}"

        # Flag OFF → RENEWAL for U (newer ts, future expiry) → still 402 (flag OFF == Phase A)
        put_cfg(h, {"features": {"server_entitlements": False}})
        r = post_webhook(event("RENEWAL", uid, expires=NOW + 30 * D, ts=NOW + 2 * H))
        assert r.status_code == 200
        r = requests.post(f"{LOCAL}/sparks/generate", json=BODY, headers=uh, timeout=30)
        assert r.status_code == 402, f"flag OFF rollback expected 402, got {r.status_code}: {r.text}"
    finally:
        # Always restore
        after = put_cfg(h, {
            "free_spark_limit": saved_free_limit,
            "limits": {"premium_daily_cap": saved_premium_cap},
            "features": {"server_entitlements": False},
        })
        assert after["features"]["server_entitlements"] is False
        assert after["free_spark_limit"] == saved_free_limit
        assert after["limits"]["premium_daily_cap"] == saved_premium_cap
        # verify restored via GET
        got = requests.get(f"{LOCAL}/admin/config", headers=h, timeout=20).json()
        assert got["features"]["server_entitlements"] is False
        assert got["free_spark_limit"] == saved_free_limit
        assert got["limits"]["premium_daily_cap"] == saved_premium_cap


# ---------- 5. Regression spot checks
def test_guest_sparks_usage():
    guest_id = f"guest-{uuid.uuid4().hex[:16]}"
    r = requests.get(
        f"{LOCAL}/sparks/usage", headers={"X-Guest-ID": guest_id, "X-Real-IP": unique_ip()}, timeout=20
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "used" in data and "limit" in data


def test_admin_config_real_routing_false():
    h = admin_headers()
    r = requests.get(f"{LOCAL}/admin/config", headers=h, timeout=20)
    assert r.status_code == 200
    data = r.json()
    assert data["features"]["real_routing"] is False
