"""Verification pass — Experience Builder inputs actually reach the recommendation engine and shape its output.

Two layers:
1. Prompt-level (LLM mocked): the exact prompt sent to Claude contains every builder field, the resolved
   weekday/time, and the SURPRISE_ME mode — and a legacy Couple request sends none of it.
2. Output-level (live engine): deterministic post-processing (per-person cost, travel-leg mode) is driven
   by party_size / transport, and the plan honours interests + duration.
"""
import asyncio
import json
import os
import re
import sys
import uuid

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import recommend  # noqa: E402
from server import GenerateIn  # noqa: E402

BASE_URL = os.environ["SPARKS_TEST_BASE_URL"].rstrip("/")
API = f"{BASE_URL}/api"
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
AI = {"model": "claude-sonnet-4-6", "guidance": ""}

FAKE_VENUES = [
    {"id": "v1", "name": "Cafe One", "address": "1 Main St", "lat": 30.2672, "lng": -97.7431, "rating": 4.5, "hours": None, "maps_url": None, "distance_miles": 0.3, "types": ["cafe"]},
    {"id": "v2", "name": "Park Two", "address": "2 Park Rd", "lat": 30.2750, "lng": -97.7400, "rating": 4.7, "hours": None, "maps_url": None, "distance_miles": 0.9, "types": ["park"]},
]
FAKE_REPLY = json.dumps(
    {
        "sparks": [
            {
                "title": "T1",
                "emoji": "✨",
                "tagline": "A → B",
                "description": "d",
                "primary_vibe": "Fun",
                "vibe_tags": [],
                "estimated_cost": "$40",
                "estimated_duration": "2 hours",
                "why": "w",
                "activities": [
                    {"name": "Coffee", "venue_id": "v1", "start_time": "10:00 AM", "end_time": "11:00 AM", "estimated_cost": "$20"},
                    {"name": "Walk", "venue_id": "v2", "start_time": "11:00 AM", "end_time": "12:00 PM", "estimated_cost": "$40"},
                ],
            }
        ]
    }
)


class _Capture:
    system = None
    prompt = None


async def _fake_llm(system, prompt, model):
    _Capture.system, _Capture.prompt = system, prompt
    return FAKE_REPLY


async def _fake_gather(lat, lng, radius, vibes):
    return FAKE_VENUES


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(recommend, "llm_complete", _fake_llm)
    monkeypatch.setattr(recommend, "gather_venues", _fake_gather)
    _Capture.system = _Capture.prompt = None

    def run(body: dict):
        g = GenerateIn(**body)
        sparks = asyncio.run(
            recommend.generate_sparks(
                relationship_type=g.relationship_type.lower(),
                vibes=g.vibes,
                budget=g.budget,
                distance=g.distance,
                location=g.location,
                exclude_titles=[],
                history={},
                date_label=g.date_label,
                time_label=g.time_label,
                ai_settings=AI,
                occasion=g.occasion,
                surprise=g.surprise,
                experience=g.experience_context(),
            )
        )
        ctx = json.loads(_Capture.prompt.split("CONTEXT:\n", 1)[1].split("\n\nVENUES", 1)[0])
        return sparks, ctx

    return run


# ---------------------------------------------------------------- 1. prompt-level: every builder field is in what the model sees
def test_builder_fields_are_in_the_prompt_context(engine):
    body = {
        "relationship_type": "family",
        "vibes": ["fun"],
        "budget": "100plus",
        "distance": "10",
        "location": AUSTIN,
        "experience_type": "family",
        "party_size": 5,
        "budget_amount": 250,
        "duration_hours": 3,
        "interests": ["Kid-friendly", "Tacos"],
        "transport": "walk",
        "scheduled_at": "2026-06-27T15:00:00Z",  # Saturday 10:00 AM CT
        "date_label": "This Weekend",
        "time_label": "10:00 AM",
    }
    sparks, ctx = engine(body)
    d = ctx["experience_details"]
    assert d["party_size"] == 5
    assert d["budget_amount"] == 250
    assert d["duration_hours"] == 3
    assert d["interests"] == ["Kid-friendly", "Tacos"]
    assert d["transport"] == "walk"
    assert d["scheduled_at"] == body["scheduled_at"]
    assert "family" in d["experience_type"].lower()
    assert "Saturday" in ctx["when"] and "open" in ctx["when"]  # concrete day/time so the model respects hours
    assert ctx["mode"] == "NORMAL"
    # the system prompt instructs the model how to use each of these inputs
    for word in ("party_size", "duration_hours", "budget_amount", "interests", "transport"):
        assert word in _Capture.system
    # and the deterministic output layer is driven by the same inputs
    sp = sparks[0]
    assert sp["travel_legs"] and all(l["mode"] == "walk" for l in sp["travel_legs"])
    assert sp["total_estimated_cost"] == 60.0 and sp["per_person_cost"] == 12.0  # 60 / party_size 5


def test_surprise_me_switches_mode_and_lets_model_pick_vibes(engine):
    _, ctx = engine({"relationship_type": "friends", "vibes": [], "budget": "50-100", "distance": "10", "location": AUSTIN, "surprise_me": True, "party_size": 3, "budget_amount": 100, "duration_hours": 4})
    assert ctx["mode"] == "SURPRISE_ME"
    assert ctx["desired_vibes"] == "you choose (SURPRISE_ME)"
    assert ctx["experience_details"] == {"party_size": 3, "budget_amount": 100, "duration_hours": 4}
    assert "SURPRISE_ME mode" in _Capture.system


def test_legacy_couple_request_sends_no_builder_context(engine):
    sparks, ctx = engine({"relationship_type": "partner", "vibes": ["romantic"], "budget": "25-50", "distance": "10", "location": AUSTIN})
    assert "experience_details" not in ctx
    assert ctx["mode"] == "NORMAL" and ctx["when"] == "not chosen yet"
    sp = sparks[0]
    assert sp["per_person_cost"] is None  # no party_size → no per-person figure
    assert all(l["mode"] == "drive" for l in sp["travel_legs"])  # default transport


def test_transport_changes_travel_estimates(engine):
    base = {"relationship_type": "friends", "vibes": ["fun"], "budget": "25-50", "distance": "10", "location": AUSTIN, "experience_type": "friends"}
    walk, _ = engine({**base, "transport": "walk"})
    drive, _ = engine({**base, "transport": "drive"})
    assert walk[0]["total_travel_miles"] == drive[0]["total_travel_miles"]
    assert walk[0]["total_travel_minutes"] > drive[0]["total_travel_minutes"]


# ---------------------------------------------------------------- 2. live engine: inputs visibly shape the generated plan
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _hours(text: str | None) -> float | None:
    if not text:
        return None
    t = text.lower()
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None
    h = max(nums)
    if "min" in t and "hour" not in t and "hr" not in t:
        h = h / 60
    return h


def test_live_generation_reflects_builder_inputs(s):
    guest = f"guest-{uuid.uuid4().hex[:12]}"
    body = {
        "relationship_type": "friends",
        "vibes": ["foodie"],
        "budget": "50-100",
        "distance": "10",
        "location": AUSTIN,
        "experience_type": "friends",
        "party_size": 6,
        "budget_amount": 90,
        "duration_hours": 2,
        "interests": ["Tacos"],
        "transport": "walk",
        "scheduled_at": "2026-06-27T17:30:00Z",
    }
    r = s.post(f"{API}/sparks/generate", headers={"X-Guest-ID": guest, "X-Premium": "1"}, json=body, timeout=170)
    assert r.status_code == 200, r.text
    sparks = r.json()["sparks"]
    assert len(sparks) == 3
    blob = json.dumps(sparks).lower()
    assert "taco" in blob, "interest 'Tacos' did not surface anywhere in the generated plans"
    for sp in sparks:
        # deterministic engine outputs driven by builder inputs
        for leg in sp["travel_legs"]:
            assert leg["mode"] == "walk"
        if sp["total_estimated_cost"] is not None:
            assert sp["per_person_cost"] == round(sp["total_estimated_cost"] / 6, 2)
        # model honoured the duration window (allow a little slack for "2–2.5 hours" style answers)
        h = _hours(sp["estimated_duration"])
        assert h is None or h <= 2.5, sp["estimated_duration"]
        # and the budget amount
        if sp["total_estimated_cost"] is not None:
            assert sp["total_estimated_cost"] <= 90 * 1.15, sp["total_estimated_cost"]
