"""Increment 3 — Experience Builder tests (inputs reach the engine; flags; legacy & surprise intact)."""
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from recommend import when_text  # noqa: E402
from server import GenerateIn  # noqa: E402

BASE_URL = os.environ["SPARKS_TEST_BASE_URL"].rstrip("/")
API = f"{BASE_URL}/api"
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
ADMIN = {"email": os.environ["SPARKS_TEST_ADMIN_EMAIL"], "password": os.environ["SPARKS_TEST_ADMIN_PASSWORD"]}
BASE = {"relationship_type": "partner", "vibes": ["romantic"], "budget": "25-50", "distance": "10", "location": AUSTIN}


# ---------------------------------------------------------------- unit: each builder input is recognised
@pytest.mark.parametrize(
    "field,value",
    [("party_size", 4), ("budget_amount", 150.0), ("duration_hours", 3.0), ("interests", ["live music", "tacos"]), ("transport", "walk"), ("scheduled_at", "2026-06-27T19:00:00Z")],
)
def test_builder_field_reaches_experience_context(field, value):
    g = GenerateIn(**{**BASE, field: value})
    assert g.experience_context()[field] == value
    assert len(g.experience_context()) == 1  # nothing else leaks into the prompt


@pytest.mark.parametrize("profile,party", [("couple", 2), ("friends", 5), ("family", 4), ("celebration", 8), ("travel", 2), ("solo", 1)])
def test_profiles_with_party_size(profile, party):
    g = GenerateIn(**{**BASE, "experience_type": profile, "party_size": party})
    ctx = g.experience_context()
    assert ctx == {"experience_type": profile, "party_size": party}


def test_surprise_me_simplified_request_needs_no_vibes_or_interests():
    g = GenerateIn(relationship_type="friends", vibes=[], budget="50-100", distance="10", location=AUSTIN, surprise_me=True, budget_amount=100, duration_hours=4, party_size=3, scheduled_at="2026-06-27T14:00:00Z")
    assert g.experience_context()["surprise_me"] is True
    assert g.interests == [] and g.transport is None
    assert g.resolved_experience_type() == "friends"  # profile still derived from company, not from the preference


def test_legacy_couple_payload_still_minimal():
    g = GenerateIn(**BASE)
    assert g.experience_context() == {} and g.party_size is None and g.budget_amount is None


def test_existing_surprise_mode_unaffected_by_builder_fields():
    g = GenerateIn(**{**BASE, "surprise": True, "party_size": 2, "transport": "drive", "duration_hours": 3})
    assert g.surprise is True and g.surprise_me is False and g.resolved_experience_type() == "couple"


@pytest.mark.parametrize("bad", [{"party_size": 0}, {"party_size": 51}, {"budget_amount": -1}, {"duration_hours": 0}, {"duration_hours": 25}, {"transport": "x" * 17}])
def test_builder_validation(bad):
    with pytest.raises(Exception):
        GenerateIn(**{**BASE, **bad})


def test_when_text_prefers_scheduled_at_and_mentions_hours():
    t = when_text("2026-06-27T19:00:00Z", "Today", "6:00 PM")
    assert "Saturday" in t and "7:00 PM" in t and "open" in t
    assert when_text(None, "Today", "6:00 PM") == "Today 6:00 PM"
    assert when_text("not-a-date", None, None) == "not chosen yet"


# ---------------------------------------------------------------- API: flags + full builder generation
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def test_builder_flag_present_and_independent(s):
    r = s.post(f"{API}/auth/login", json=ADMIN)
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pub = s.get(f"{API}/config/public").json()["features"]
    assert pub["experience_builder"] is True and pub["experience_profiles"] is True
    off = s.put(f"{API}/admin/config", headers=h, json={"features": {"experience_builder": False}}).json()["features"]
    assert off["experience_builder"] is False and off["experience_profiles"] is True  # independent
    on = s.put(f"{API}/admin/config", headers=h, json={"features": {"experience_builder": True}}).json()["features"]
    assert on["experience_builder"] is True and on["experience_profiles"] is True


def test_full_builder_generation_persists_inputs(s):
    guest = f"guest-{uuid.uuid4().hex[:12]}"
    body = {
        "relationship_type": "family",
        "vibes": ["fun", "relaxing"],
        "budget": "100plus",
        "distance": "25",
        "location": AUSTIN,
        "experience_type": "family",
        "party_size": 5,
        "budget_amount": 250,
        "duration_hours": 5,
        "interests": ["Kid-friendly", "Outdoors"],
        "transport": "drive",
        "date_label": "This Weekend",
        "time_label": "10:00 AM",
        "scheduled_at": "2026-06-27T15:00:00Z",
    }
    r = s.post(f"{API}/sparks/generate", headers={"X-Guest-ID": guest, "X-Premium": "1"}, json=body, timeout=170)
    assert r.status_code == 200, r.text
    sp = r.json()["sparks"][0]
    for k in ("experience_type", "party_size", "budget_amount", "duration_hours", "interests", "transport", "date_label", "time_label", "scheduled_at"):
        assert sp[k] == body[k], k
    assert sp["surprise"] is False and sp["surprise_me"] is False
    if sp["total_estimated_cost"] is not None:
        assert sp["per_person_cost"] == round(sp["total_estimated_cost"] / 5, 2)
    for leg in sp["travel_legs"]:
        assert leg["mode"] == "drive"
    # scheduled_at from the builder is visible through the existing detail endpoint
    d = s.get(f"{API}/sparks/{sp['id']}", headers={"X-Guest-ID": guest}).json()
    assert d["scheduled_at"] == body["scheduled_at"] and d["party_size"] == 5
