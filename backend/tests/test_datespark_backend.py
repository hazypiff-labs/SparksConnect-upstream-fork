"""Date Spark backend regression tests."""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vibe-finder-75.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@datespark.app"
ADMIN_PASSWORD = "SparkAdmin2026!"

GUEST_ID = f"guest-{uuid.uuid4().hex[:16]}"
GUEST_ID_2 = f"guest-{uuid.uuid4().hex[:16]}"
GUEST_ID_LIMIT = f"guest-{uuid.uuid4().hex[:16]}"


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="session")
def admin_token(s):
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def generated_spark_ids(s):
    """Generate once and reuse for spark CRUD tests."""
    r = s.post(
        f"{API}/sparks/generate",
        headers={"X-Guest-ID": GUEST_ID},
        json={
            "relationship_type": "Partner",
            "vibes": ["Romantic", "Chill"],
            "budget": "$25-$50",
            "distance": "10 miles",
            "location": {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431},
        },
        timeout=120,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    ids = [sp["id"] for sp in data["sparks"]]
    assert len(ids) == 3
    return ids


# ---------- Public config
def test_public_config(s):
    r = s.get(f"{API}/config/public")
    assert r.status_code == 200
    d = r.json()
    for k in ("free_spark_limit", "premium_price", "trial_days", "promo_message", "featured_experiences"):
        assert k in d
    assert isinstance(d["featured_experiences"], list)


# ---------- Geocoding
def test_geocode_austin(s):
    r = s.get(f"{API}/places/geocode", params={"q": "Austin"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "label" in d and "lat" in d and "lng" in d
    assert -100 < d["lng"] < -95 and 29 < d["lat"] < 32


# ---------- Identity guard
def test_generate_requires_identity(s):
    r = s.post(f"{API}/sparks/generate", json={"relationship_type": "Partner", "vibes": ["Chill"], "budget": "$0", "distance": "5 miles", "location": {}})
    assert r.status_code == 400


# ---------- Spark generation (session fixture triggers it)
def test_sparks_generated_have_expected_shape(generated_spark_ids, s):
    assert len(generated_spark_ids) == 3
    # Fetch one and validate
    r = s.get(f"{API}/sparks/{generated_spark_ids[0]}", headers={"X-Guest-ID": GUEST_ID})
    assert r.status_code == 200
    d = r.json()
    for k in ("id", "title", "emoji", "activities", "is_owner"):
        assert k in d, f"missing {k}"
    assert d["is_owner"] is True


def test_sparks_usage_tracks(s):
    r = s.get(f"{API}/sparks/usage", headers={"X-Guest-ID": GUEST_ID})
    assert r.status_code == 200
    d = r.json()
    assert d["used"] >= 1
    assert "limit" in d


def test_shared_public_view(generated_spark_ids, s):
    # No identity headers
    fresh = requests.Session()
    r = fresh.get(f"{API}/shared/{generated_spark_ids[0]}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "title" in d


def test_save_and_unsave(generated_spark_ids, s):
    sid = generated_spark_ids[0]
    h = {"X-Guest-ID": GUEST_ID}
    r = s.post(f"{API}/sparks/{sid}/save", headers=h)
    assert r.status_code == 200 and r.json()["saved"] is True

    r = s.get(f"{API}/sparks/mine", headers=h)
    assert r.status_code == 200
    mine = r.json()
    assert any(sp["id"] == sid for sp in mine["saved"])

    r = s.delete(f"{API}/sparks/{sid}/save", headers=h)
    assert r.status_code == 200 and r.json()["saved"] is False


def test_schedule_and_share(generated_spark_ids, s):
    sid = generated_spark_ids[1]
    h = {"X-Guest-ID": GUEST_ID}
    r = s.put(f"{API}/sparks/{sid}/schedule", headers=h, json={"date_label": "Today", "time_label": "7 PM"})
    assert r.status_code == 200
    r = s.post(f"{API}/sparks/{sid}/share", headers=h, json={"date_label": "Today", "time_label": "7 PM"})
    assert r.status_code == 200
    d = r.json()
    assert "invitation" in d and "I found something for us" in d["invitation"]
    assert d["share_url"].startswith("datespark://spark/")


def test_complete_spark(generated_spark_ids, s):
    sid = generated_spark_ids[2]
    h = {"X-Guest-ID": GUEST_ID}
    r = s.post(f"{API}/sparks/{sid}/complete", headers=h)
    assert r.status_code == 200
    # Verify via /mine
    r = s.get(f"{API}/sparks/mine", headers=h)
    completed_ids = [sp["id"] for sp in r.json()["completed"]]
    assert sid in completed_ids


def test_events_endpoint(s):
    r = s.post(f"{API}/events", headers={"X-Guest-ID": GUEST_ID}, json={"event": "test_event", "props": {"k": "v"}})
    assert r.status_code == 200 and r.json()["ok"] is True


# ---------- Free limit enforcement (uses separate guest with limit temporarily lowered)
def test_free_limit_enforcement_and_premium_claim_is_not_a_bypass(s, admin_token):
    ah = {"Authorization": f"Bearer {admin_token}"}
    # Lower limit to 0 so first generation is blocked
    r = s.put(f"{API}/admin/config", headers=ah, json={"free_spark_limit": 0})
    assert r.status_code == 200

    try:
        h = {"X-Guest-ID": GUEST_ID_LIMIT}
        payload = {
            "relationship_type": "Partner",
            "vibes": ["Chill"],
            "budget": "$0-$25",
            "distance": "5 miles",
            "location": {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431},
        }
        r = s.post(f"{API}/sparks/generate", headers=h, json=payload, timeout=30)
        assert r.status_code == 402, f"expected 402 got {r.status_code}: {r.text[:200]}"

        # Phase A: a client-side X-Premium claim is NOT a bypass — same free quota applies (402, no LLM call)
        r = s.post(f"{API}/sparks/generate", headers={**h, "X-Premium": "1"}, json=payload, timeout=30)
        assert r.status_code == 402, r.text
    finally:
        # Restore
        r = s.put(f"{API}/admin/config", headers=ah, json={"free_spark_limit": 3})
        assert r.status_code == 200
        assert r.json()["free_spark_limit"] == 3


# ---------- Auth
def test_signup_login_me_and_delete(s):
    email = f"test_{uuid.uuid4().hex[:8]}@datespark.app"
    guest = f"guest-{uuid.uuid4().hex[:16]}"

    # Track an event under guest so migration has something to move
    s.post(f"{API}/events", headers={"X-Guest-ID": guest}, json={"event": "guest_visit"})

    # Duplicate email test setup — signup once
    r = s.post(f"{API}/auth/signup", headers={"X-Guest-ID": guest}, json={"name": "Test User", "email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert r.json()["user"]["email"] == email

    # Duplicate
    r = s.post(f"{API}/auth/signup", json={"name": "Test User", "email": email, "password": "password123"})
    assert r.status_code == 409

    # Wrong password
    r = s.post(f"{API}/auth/login", json={"email": email, "password": "wrongpass"})
    assert r.status_code == 401

    # Correct login
    r = s.post(f"{API}/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200

    # /me
    r = s.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == email

    # Delete account
    r = s.delete(f"{API}/auth/account", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200

    # Token now fails
    r = s.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# ---------- Admin
def test_admin_stats_and_config(s, admin_token):
    ah = {"Authorization": f"Bearer {admin_token}"}
    r = s.get(f"{API}/admin/stats", headers=ah)
    assert r.status_code == 200
    d = r.json()
    for k in ("total_users", "sparks_generated", "mrr", "conversion_rate"):
        assert k in d

    r = s.get(f"{API}/admin/config", headers=ah)
    assert r.status_code == 200
    assert "free_spark_limit" in r.json()


def test_admin_forbidden_for_non_admin(s):
    email = f"user_{uuid.uuid4().hex[:8]}@datespark.app"
    r = s.post(f"{API}/auth/signup", json={"name": "Reg", "email": email, "password": "password123"})
    assert r.status_code == 200
    tok = r.json()["access_token"]
    r = s.get(f"{API}/admin/stats", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    # Cleanup
    s.delete(f"{API}/auth/account", headers={"Authorization": f"Bearer {tok}"})
