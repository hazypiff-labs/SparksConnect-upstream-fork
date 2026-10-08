"""Increment 1 — Experience Engine foundation tests.

Unit tests cover the pure helpers (no network). API tests hit the running backend and
verify backward compatibility of POST /api/sparks/generate plus the additive fields.
"""
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from recommend import compute_travel_legs, cost_rollup, parse_cost, resolve_mode  # noqa: E402

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vibe-finder-75.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}


# ----------------------------------------------------------------- unit: parse_cost
@pytest.mark.parametrize(
    "text,expected",
    [("$35", 35.0), ("$25–$50", 37.5), ("$25-$50", 37.5), ("Free", 0.0), ("FREE", 0.0), ("about $12.50", 12.5), ("$1,200", 1200.0), (None, None), ("", None), ("varies", None)],
)
def test_parse_cost(text, expected):
    assert parse_cost(text) == expected


# ----------------------------------------------------------------- unit: travel legs
def _act(lat, lng, cost=None):
    return {"activity_name": "x", "lat": lat, "lng": lng, "estimated_cost": cost}


def test_travel_legs_between_verified_stops_drive_default():
    acts = [_act(30.2672, -97.7431), _act(30.2500, -97.7500), _act(30.2400, -97.7300)]
    legs = compute_travel_legs(acts, None)
    assert len(legs) == 2
    assert legs[0]["from_index"] == 0 and legs[0]["to_index"] == 1
    assert legs[0]["mode"] == "drive"
    assert 1.0 < legs[0]["miles"] < 1.6  # ~1.26 mi haversine
    assert legs[0]["minutes"] >= 1
    assert "Drive" in legs[0]["label"]


def test_travel_legs_walk_is_slower_than_drive():
    acts = [_act(30.2672, -97.7431), _act(30.2500, -97.7500)]
    walk = compute_travel_legs(acts, "walk")[0]["minutes"]
    drive = compute_travel_legs(acts, "drive")[0]["minutes"]
    assert walk > drive


def test_travel_legs_skip_unverified_stops():
    acts = [_act(30.2672, -97.7431), _act(None, None), _act(30.2400, -97.7300)]
    assert compute_travel_legs(acts, "transit") == []
    assert compute_travel_legs([], "walk") == []
    assert compute_travel_legs([_act(1, 1)], "walk") == []


def test_travel_legs_unknown_transport_falls_back_to_drive():
    acts = [_act(30.2672, -97.7431), _act(30.2500, -97.7500)]
    assert compute_travel_legs(acts, "teleport")[0]["mode"] == "drive"


# ----------------------------------------------------------------- unit: cost roll-up
def test_cost_rollup_sums_known_and_flags_unknown():
    acts = [_act(0, 0, "$20"), _act(0, 0, "$25–$35"), _act(0, 0, None)]
    r = cost_rollup(acts, 2)
    assert r["total_estimated_cost"] == 50.0
    assert r["per_person_cost"] == 25.0
    assert r["priced_stops"] == 2 and r["unpriced_stops"] == 1
    assert r["complete"] is False


def test_cost_rollup_never_invents_prices():
    r = cost_rollup([_act(0, 0, None), _act(0, 0, "varies")], 4)
    assert r["total_estimated_cost"] is None and r["per_person_cost"] is None
    assert r["unpriced_stops"] == 2 and r["complete"] is False


def test_cost_rollup_without_party_size_has_no_per_person():
    r = cost_rollup([_act(0, 0, "$10"), _act(0, 0, "Free")], None)
    assert r["total_estimated_cost"] == 10.0 and r["per_person_cost"] is None and r["complete"] is True


# ----------------------------------------------------------------- unit: mode precedence
def test_resolve_mode_precedence_keeps_existing_modes_first():
    assert resolve_mode(True, "birthday", True) == "SURPRISE"
    assert resolve_mode(False, "birthday", True) == "OCCASION"
    assert resolve_mode(False, None, True) == "SURPRISE_ME"
    assert resolve_mode(False, None, False) == "NORMAL"


# ----------------------------------------------------------------- API: backward compatibility
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json", "X-Premium": "1"})
    return sess


def test_generate_rejects_missing_vibes_without_surprise_me(s):
    r = s.post(f"{API}/sparks/generate", headers={"X-Guest-ID": f"guest-{uuid.uuid4().hex[:12]}"}, json={"relationship_type": "partner", "vibes": [], "budget": "25-50", "distance": "10", "location": AUSTIN})
    assert r.status_code == 422


def test_generate_rejects_invalid_new_field_values(s):
    r = s.post(f"{API}/sparks/generate", headers={"X-Guest-ID": f"guest-{uuid.uuid4().hex[:12]}"}, json={"relationship_type": "partner", "vibes": ["romantic"], "budget": "25-50", "distance": "10", "location": AUSTIN, "party_size": 0})
    assert r.status_code == 422


def test_generate_with_experience_fields_and_surprise_me(s):
    guest = f"guest-{uuid.uuid4().hex[:12]}"
    body = {
        "relationship_type": "friends",
        "vibes": [],  # SURPRISE_ME picks the vibe
        "budget": "50-100",
        "distance": "10",
        "location": AUSTIN,
        "experience_type": "friends",
        "party_size": 4,
        "budget_amount": 150,
        "duration_hours": 3,
        "interests": ["live music", "tacos"],
        "transport": "walk",
        "surprise_me": True,
    }
    r = s.post(f"{API}/sparks/generate", headers={"X-Guest-ID": guest}, json=body, timeout=170)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["sparks"]) == 3
    sp = data["sparks"][0]
    # additive fields present
    assert sp["experience_type"] == "friends"
    assert sp["party_size"] == 4 and sp["budget_amount"] == 150 and sp["duration_hours"] == 3
    assert sp["interests"] == ["live music", "tacos"] and sp["transport"] == "walk"
    assert sp["surprise_me"] is True and sp["surprise"] is False  # existing surprise untouched
    assert isinstance(sp["travel_legs"], list)
    for leg in sp["travel_legs"]:
        assert leg["mode"] == "walk" and leg["miles"] >= 0 and leg["minutes"] >= 0
    assert "total_estimated_cost" in sp and "per_person_cost" in sp and "unpriced_stops" in sp
    if sp["total_estimated_cost"] is not None:
        assert sp["per_person_cost"] == round(sp["total_estimated_cost"] / 4, 2)
    # legacy fields still present and well-formed
    for key in ("id", "title", "emoji", "description", "primary_vibe", "estimated_cost", "estimated_duration", "why", "activities", "location_label", "needs_verification", "revealed_steps"):
        assert key in sp
    assert sp["revealed_steps"] == len(sp["activities"])  # not a mystery spark
    # persisted and readable through the existing detail endpoint
    d = s.get(f"{API}/sparks/{sp['id']}", headers={"X-Guest-ID": guest}).json()
    assert d["experience_type"] == "friends" and d["travel_legs"] == sp["travel_legs"] and d["is_owner"] is True
