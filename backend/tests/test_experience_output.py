"""Increment 4 — Experience Output Upgrade (backend side).

Covers: the `experience_output` flag (default on, admin toggle, independent of the other flags), the shared
endpoint exposing travel/cost fields, surprise-recipient redaction of those fields, and backward compatibility
for sparks that predate the engine-output fields.
"""
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from recommend import compute_travel_legs, cost_rollup  # noqa: E402
from server import DEFAULT_CONFIG, OUTPUT_FIELDS, redact_for_recipient  # noqa: E402

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vibe-finder-75.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
ADMIN = {"email": "admin@datespark.app", "password": "SparkAdmin2026!"}

STOPS = [
    {"activity_name": "Coffee", "lat": 30.2672, "lng": -97.7431, "estimated_cost": "$12", "start_time": "6:00 PM", "end_time": "7:00 PM"},
    {"activity_name": "Walk", "lat": 30.2750, "lng": -97.7400, "estimated_cost": None, "start_time": "7:00 PM", "end_time": "8:00 PM"},
    {"activity_name": "Dessert", "lat": 30.2800, "lng": -97.7450, "estimated_cost": "$18", "start_time": "8:00 PM", "end_time": "9:00 PM"},
]


# ---------------------------------------------------------------- unit
def test_output_flag_defaults_on_alongside_existing_flags():
    assert DEFAULT_CONFIG["features"] == {"experience_profiles": True, "experience_builder": True, "experience_output": True}


def test_cost_rollup_distinguishes_priced_and_unpriced_without_inventing():
    c = cost_rollup(STOPS, party_size=2)
    assert c["total_estimated_cost"] == 30.0 and c["per_person_cost"] == 15.0
    assert c["priced_stops"] == 2 and c["unpriced_stops"] == 1 and c["complete"] is False
    assert cost_rollup([{"estimated_cost": None}], 2)["total_estimated_cost"] is None  # nothing priced → no total at all


def test_travel_legs_are_labelled_as_mode_estimates_only():
    legs = compute_travel_legs(STOPS, "walk")
    assert [(l["from_index"], l["to_index"]) for l in legs] == [(0, 1), (1, 2)]
    for l in legs:
        assert l["mode"] == "walk" and l["minutes"] >= 1 and l["miles"] > 0
        assert "route" not in l["label"].lower()  # never implies real routing


def test_locked_recipient_loses_travel_and_cost_fields():
    spark = {
        "surprise": True,
        "revealed_steps": 1,
        "scheduled_at": "2099-01-01T20:00:00Z",
        "activities": [{"start_time": "7:00 PM", "address": "1 Main St"}, {"start_time": "8:00 PM", "address": "Secret"}],
        "location_label": "Austin",
        "travel_legs": [{"from_index": 0, "to_index": 1, "miles": 1.2, "minutes": 5, "mode": "drive", "label": "x"}],
        "total_travel_minutes": 5,
        "total_travel_miles": 1.2,
        "total_estimated_cost": 40.0,
        "per_person_cost": 20.0,
        "priced_stops": 2,
        "unpriced_stops": 0,
        "complete": True,
    }
    out = redact_for_recipient(dict(spark))
    assert out["locked_for_recipient"] is True and out["activities"] == []
    assert out["travel_legs"] == []
    for k in OUTPUT_FIELDS:
        if k != "travel_legs":
            assert out[k] is None, k
    assert out["meet_place"] == "1 Main St"  # the meeting point is still shared


def test_unlocked_or_non_surprise_keeps_output_fields():
    plain = {"surprise": False, "activities": [], "travel_legs": [{"a": 1}], "total_estimated_cost": 12.0}
    out = redact_for_recipient(dict(plain))
    assert out["locked_for_recipient"] is False and out["travel_legs"] == [{"a": 1}] and out["total_estimated_cost"] == 12.0


def test_legacy_spark_without_output_fields_redacts_cleanly():
    legacy = {"surprise": True, "revealed_steps": 1, "scheduled_at": "2099-01-01T20:00:00Z", "activities": [{"start_time": "7:00 PM"}, {}], "location_label": "Austin"}
    out = redact_for_recipient(dict(legacy))
    assert out["locked_for_recipient"] is True
    assert not any(k in out for k in OUTPUT_FIELDS)  # nothing fabricated for old documents


# ---------------------------------------------------------------- API
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


def test_output_flag_public_and_independently_toggleable(s, admin_headers):
    pub = s.get(f"{API}/config/public").json()["features"]
    assert pub["experience_output"] is True
    try:
        off = s.put(f"{API}/admin/config", headers=admin_headers, json={"features": {"experience_output": False}}).json()["features"]
        assert off == {"experience_profiles": True, "experience_builder": True, "experience_output": False}
        assert s.get(f"{API}/config/public").json()["features"]["experience_output"] is False
        # flipping the others leaves output alone
        mixed = s.put(f"{API}/admin/config", headers=admin_headers, json={"features": {"experience_builder": False}}).json()["features"]
        assert mixed == {"experience_profiles": True, "experience_builder": False, "experience_output": False}
    finally:
        on = s.put(f"{API}/admin/config", headers=admin_headers, json={"features": {"experience_profiles": True, "experience_builder": True, "experience_output": True}}).json()["features"]
        assert on == {"experience_profiles": True, "experience_builder": True, "experience_output": True}


def test_shared_endpoint_exposes_output_fields_and_redacts_locked_surprise(s):
    guest = f"guest-{uuid.uuid4().hex[:12]}"
    h = {"X-Guest-ID": guest, "X-Premium": "1"}
    body = {"relationship_type": "friends", "vibes": ["fun"], "budget": "25-50", "distance": "10", "location": AUSTIN, "experience_type": "friends", "party_size": 4, "transport": "walk"}
    r = s.post(f"{API}/sparks/generate", headers=h, json=body, timeout=170)
    assert r.status_code == 200, r.text
    sp = r.json()["sparks"][0]
    for k in OUTPUT_FIELDS:
        assert k in sp, k
    shared = s.get(f"{API}/shared/{sp['id']}").json()
    assert shared["locked_for_recipient"] is False
    assert shared["travel_legs"] == sp["travel_legs"] and shared["total_estimated_cost"] == sp["total_estimated_cost"]
    assert shared["party_size"] == 4 and shared["transport"] == "walk"
    if sp["total_estimated_cost"] is not None:
        assert shared["per_person_cost"] == round(sp["total_estimated_cost"] / 4, 2)

    # surprise: owner sees everything, recipient sees no legs/costs until unlocked
    sb = {"relationship_type": "partner", "vibes": ["romantic"], "budget": "50-100", "distance": "10", "location": AUSTIN, "surprise": True, "scheduled_at": "2099-01-01T01:00:00Z", "transport": "drive"}
    r = s.post(f"{API}/sparks/generate", headers=h, json=sb, timeout=170)
    assert r.status_code == 200, r.text
    sur = r.json()["sparks"][0]
    owner = s.get(f"{API}/sparks/{sur['id']}", headers={"X-Guest-ID": guest}).json()
    assert owner["is_owner"] is True and owner["travel_legs"] == sur["travel_legs"] and len(owner["activities"]) == len(sur["activities"])
    recipient = s.get(f"{API}/shared/{sur['id']}").json()
    assert recipient["locked_for_recipient"] is True and recipient["activities"] == [] and recipient["travel_legs"] == []
    assert recipient["total_estimated_cost"] is None and recipient["per_person_cost"] is None and recipient["total_travel_miles"] is None
    other = s.get(f"{API}/sparks/{sur['id']}", headers={"X-Guest-ID": f"guest-{uuid.uuid4().hex[:12]}"}).json()
    assert other["is_owner"] is False and other["travel_legs"] == [] and other["total_estimated_cost"] is None
