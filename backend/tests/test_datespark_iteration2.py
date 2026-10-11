"""Date Spark iteration 2 tests: Google session auth, occasion, surprise sparks & invitations."""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ["SPARKS_TEST_BASE_URL"].rstrip("/")
API = f"{BASE_URL}/api"

OWNER_GUEST = f"guest-{uuid.uuid4().hex[:16]}"
OTHER_GUEST = f"guest-{uuid.uuid4().hex[:16]}"


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---------- Google session with bogus id must reject
def test_emergent_session_exchange_removed_and_google_bogus_token_401(s):
    # The Emergent demo-auth exchange is gone (audit H3); Google sign-in verifies ID tokens server-side.
    assert s.post(f"{API}/auth/session", json={"session_id": "bogus"}).status_code in (404, 405)
    r = s.post(f"{API}/auth/google", json={"id_token": "bogus.token.value"})
    assert r.status_code == 401, r.text


# ---------- Surprise + occasion generation as premium guest
@pytest.fixture(scope="session")
def surprise_sparks(s):
    payload = {
        "relationship_type": "Partner",
        "vibes": ["Romantic", "Adventurous"],
        "budget": "$25-$50",
        "distance": "10 miles",
        "location": {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431},
        "occasion": "anniversary",
        "surprise": True,
    }
    r = s.post(
        f"{API}/sparks/generate",
        headers={"X-Guest-ID": OWNER_GUEST, "X-Premium": "1"},
        json=payload,
        timeout=180,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["sparks"]) == 3
    for sp in data["sparks"]:
        assert sp.get("surprise") is True
        assert sp.get("revealed_steps") == 1
        assert isinstance(sp.get("dress_code"), str) and sp["dress_code"]
        assert sp.get("occasion") == "anniversary"
    return data["sparks"]


def test_surprise_sparks_shape(surprise_sparks):
    ids = [sp["id"] for sp in surprise_sparks]
    assert len(set(ids)) == 3


def test_non_owner_gets_locked_view(s, surprise_sparks):
    sid = surprise_sparks[0]["id"]
    r = s.get(f"{API}/sparks/{sid}", headers={"X-Guest-ID": OTHER_GUEST})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("locked_for_recipient") is True
    assert d.get("activities") == []
    assert d.get("is_owner") is False
    # Meet info must be present, dress code allowed too
    assert d.get("meet_place") is not None or d.get("location_label")


def test_owner_full_view(s, surprise_sparks):
    sid = surprise_sparks[0]["id"]
    r = s.get(f"{API}/sparks/{sid}", headers={"X-Guest-ID": OWNER_GUEST})
    assert r.status_code == 200
    d = r.json()
    assert d.get("is_owner") is True
    assert isinstance(d.get("activities"), list) and len(d["activities"]) >= 1
    # Owner should not be locked
    assert d.get("locked_for_recipient") in (False, None)


def test_reveal_increments_and_non_owner_404(s, surprise_sparks):
    sid = surprise_sparks[1]["id"]
    # Non-owner cannot reveal
    r = s.put(f"{API}/sparks/{sid}/reveal", headers={"X-Guest-ID": OTHER_GUEST})
    assert r.status_code == 404, r.text
    # Owner increments
    r = s.put(f"{API}/sparks/{sid}/reveal", headers={"X-Guest-ID": OWNER_GUEST})
    assert r.status_code == 200
    d = r.json()
    assert d["revealed_steps"] >= 2
    assert d["total"] >= d["revealed_steps"]


def test_share_with_past_scheduled_unlocks_recipient(s, surprise_sparks):
    sid = surprise_sparks[2]["id"]
    share_url = f"exp://test/--/spark/{sid}"
    body = {
        "date_label": "Today",
        "time_label": "6 PM",
        "scheduled_at": "2026-01-01T18:00:00Z",
        "share_url": share_url,
    }
    r = s.post(f"{API}/sparks/{sid}/share", headers={"X-Guest-ID": OWNER_GUEST}, json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert share_url in d["invitation"]
    assert "Dress code" in d["invitation"]
    assert d["share_url"] == share_url

    # After share with past scheduled_at, non-owner should see full plan
    r = s.get(f"{API}/sparks/{sid}", headers={"X-Guest-ID": OTHER_GUEST})
    assert r.status_code == 200
    d2 = r.json()
    assert d2.get("locked_for_recipient") is False
    assert isinstance(d2.get("activities"), list) and len(d2["activities"]) >= 1


def test_shared_public_endpoint_redacts_surprise(s, surprise_sparks):
    """A surprise spark that hasn't been shared with a past scheduled time must remain locked on /shared/{id}."""
    sid = surprise_sparks[0]["id"]  # not shared / not past
    fresh = requests.Session()
    r = fresh.get(f"{API}/shared/{sid}")
    assert r.status_code == 200, r.text
    d = r.json()
    # Expect redaction: activities empty AND locked flag true
    assert d.get("locked_for_recipient") is True
    assert d.get("activities") == []


def test_shared_public_endpoint_shows_after_scheduled_past(s, surprise_sparks):
    sid = surprise_sparks[2]["id"]  # was shared with past scheduled_at
    fresh = requests.Session()
    r = fresh.get(f"{API}/shared/{sid}")
    assert r.status_code == 200
    d = r.json()
    assert d.get("locked_for_recipient") is False
    assert isinstance(d.get("activities"), list) and len(d["activities"]) >= 1
