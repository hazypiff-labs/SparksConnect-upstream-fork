"""Increment 2 — Experience Profiles tests (feature flag, profile derivation, API acceptance)."""
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import GenerateIn  # noqa: E402

BASE_URL = os.environ["SPARKS_TEST_BASE_URL"].rstrip("/")
API = f"{BASE_URL}/api"
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
ADMIN = {"email": os.environ["SPARKS_TEST_ADMIN_EMAIL"], "password": os.environ["SPARKS_TEST_ADMIN_PASSWORD"]}

BASE = {"relationship_type": "partner", "vibes": ["romantic"], "budget": "25-50", "distance": "10", "location": AUSTIN}


# ---------------------------------------------------------------- unit: profile derivation (no network)
@pytest.mark.parametrize("profile", ["couple", "friends", "family", "celebration", "travel", "solo"])
def test_each_profile_is_accepted_and_stored_as_experience_type(profile):
    g = GenerateIn(**{**BASE, "experience_type": profile})
    assert g.resolved_experience_type() == profile
    assert g.experience_context()["experience_type"] == profile


def test_legacy_couple_request_unchanged():
    g = GenerateIn(**BASE)
    assert g.resolved_experience_type() == "couple"
    assert g.experience_context() == {}  # nothing new reaches the prompt
    assert g.surprise is False and g.surprise_me is False


@pytest.mark.parametrize("rel,expected", [("partner", "couple"), ("date", "couple"), ("special", "couple"), ("friends", "friends"), ("group", "friends"), ("family", "family"), ("solo", "solo")])
def test_legacy_relationship_derivation(rel, expected):
    assert GenerateIn(**{**BASE, "relationship_type": rel}).resolved_experience_type() == expected


def test_existing_surprise_mode_untouched_by_profiles():
    g = GenerateIn(**{**BASE, "surprise": True, "experience_type": "friends"})
    assert g.surprise is True and g.surprise_me is False
    assert g.resolved_experience_type() == "friends"
    # surprise_me stays an independent planning preference, not a profile
    g2 = GenerateIn(**{**BASE, "vibes": [], "surprise_me": True})
    assert g2.resolved_experience_type() == "couple" and g2.surprise is False  # derived from company, not from the preference


def test_occasion_without_profile_derives_celebration():
    assert GenerateIn(**{**BASE, "occasion": "birthday"}).resolved_experience_type() == "celebration"


# ---------------------------------------------------------------- API: feature flag
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module")
def admin_headers(s):
    r = s.post(f"{API}/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_public_config_exposes_experience_profiles_flag(s):
    r = s.get(f"{API}/config/public")
    assert r.status_code == 200
    assert r.json()["features"]["experience_profiles"] is True


def test_admin_can_toggle_flag_and_restore(s, admin_headers):
    off = s.put(f"{API}/admin/config", headers=admin_headers, json={"features": {"experience_profiles": False}})
    assert off.status_code == 200 and off.json()["features"]["experience_profiles"] is False
    assert s.get(f"{API}/config/public").json()["features"]["experience_profiles"] is False
    on = s.put(f"{API}/admin/config", headers=admin_headers, json={"features": {"experience_profiles": True}})
    assert on.status_code == 200 and on.json()["features"]["experience_profiles"] is True
    # other config keys untouched by a features-only update
    assert on.json()["free_spark_limit"] == off.json()["free_spark_limit"]


# ---------------------------------------------------------------- API: one real generation per new profile family
def test_generate_solo_profile_end_to_end(s):
    guest = f"guest-{uuid.uuid4().hex[:12]}"
    body = {**BASE, "relationship_type": "solo", "vibes": ["relaxing", "creative"], "experience_type": "solo"}
    r = s.post(f"{API}/sparks/generate", headers={"X-Guest-ID": guest, "X-Premium": "1"}, json=body, timeout=170)
    assert r.status_code == 200, r.text
    sp = r.json()["sparks"][0]
    assert sp["experience_type"] == "solo" and sp["relationship_type"] == "solo"
    assert sp["surprise"] is False and sp["surprise_me"] is False
    assert sp["revealed_steps"] == len(sp["activities"]) >= 2
    assert "travel_legs" in sp and "total_estimated_cost" in sp
