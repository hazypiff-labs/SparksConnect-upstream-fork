"""Audit 2026-10-10 Wave 3 — sharing / surprise privacy and analytics minimization (HTTP against the test server)."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

from server import surprise_unlocked

API = os.environ["SPARKS_TEST_BASE_URL"] + "/api"
OWNER_ONLY = ("location", "relationship_type", "vibe", "budget", "distance", "owner_type", "owner_id", "exclude_titles", "interests", "surprise_me", "share_count", "status")
FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()


def g():
    return {"X-Guest-ID": "guest-" + uuid.uuid4().hex[:16]}


def make(h, surprise=True, scheduled_at=FUTURE, occasion=None):
    body = {"relationship_type": "partner", "vibes": ["romantic"], "budget": "under25", "distance": "10", "surprise": surprise,
            "scheduled_at": scheduled_at, "location": {"label": "Home", "lat": 40.7128, "lng": -74.006}}
    if occasion:
        body["occasion"] = occasion
    r = requests.post(f"{API}/sparks/generate", json=body, headers=h, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["sparks"][0]


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_recipient_cannot_read_surprise_through_saved_list():
    owner, recipient = g(), g()
    sp = make(owner)
    assert requests.post(f"{API}/sparks/{sp['id']}/save", headers=recipient).status_code == 200
    saved = requests.get(f"{API}/sparks/mine", headers=recipient).json()["saved"]
    item = next(x for x in saved if x["id"] == sp["id"])
    assert item["locked_for_recipient"] is True and item["activities"] == [] and item["is_owner"] is False
    assert not any(k in item for k in OWNER_ONLY)


def test_non_owner_view_never_contains_owner_inputs():
    owner = g()
    sp = make(owner, surprise=False)
    for url, h in ((f"{API}/sparks/{sp['id']}", g()), (f"{API}/shared/{sp['id']}", {})):
        out = requests.get(url, headers=h).json()
        assert out["activities"], "non-surprise plans stay fully visible"
        assert not any(k in out for k in OWNER_ONLY), [k for k in OWNER_ONLY if k in out]
    mine = requests.get(f"{API}/sparks/{sp['id']}", headers=owner).json()
    assert mine["is_owner"] is True and mine["location"]["label"] == "Home"  # the owner still sees everything


def test_owner_revealing_every_stop_unlocks_for_recipient():
    owner = g()
    sp = make(owner)
    assert requests.get(f"{API}/shared/{sp['id']}").json()["locked_for_recipient"] is True
    total = len(sp["activities"])
    for _ in range(total):
        requests.put(f"{API}/sparks/{sp['id']}/reveal", headers=owner)
    out = requests.get(f"{API}/shared/{sp['id']}").json()
    assert out["locked_for_recipient"] is False and len(out["activities"]) == total


def test_past_scheduled_time_unlocks():
    sp = make(g(), scheduled_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    assert requests.get(f"{API}/shared/{sp['id']}").json()["locked_for_recipient"] is False


@pytest.mark.parametrize("doc,expected", [
    ({"surprise": True, "activities": [{}], "revealed_steps": 1, "fully_revealed_at": None}, False),  # one-stop: locked
    ({"surprise": True, "activities": [{}], "revealed_steps": 1}, False),  # legacy one-stop
    ({"surprise": True, "activities": [{}, {}, {}], "revealed_steps": 3}, True),  # legacy fully revealed
    ({"surprise": True, "activities": [{}, {}], "revealed_steps": 2, "fully_revealed_at": None}, False),
    ({"surprise": True, "activities": [{}], "revealed_steps": 1, "fully_revealed_at": "2026-01-01T00:00:00+00:00"}, True),
    ({"surprise": False, "activities": [{}]}, True),
])
def test_surprise_unlock_rules(doc, expected):
    assert surprise_unlocked(doc) is expected


def test_analytics_keep_no_free_text_or_precise_location(db):
    h = g()
    secret = "Anniversary at 12 Private Street " + uuid.uuid4().hex
    make(h, surprise=False, occasion=secret)
    ev = db.analytics_events.find_one({"event": "sparks_generated", "owner_id": h["X-Guest-ID"]})
    flat = repr(ev["props"])
    assert secret not in flat and "Home" not in flat
    assert ev["props"]["area"] == "40.7,-74.0" and ev["props"]["has_occasion"] is True


def test_analytics_retention_index(db):
    idx = {i["name"]: i for i in db.analytics_events.list_indexes()}
    assert idx["analytics_retention"]["expireAfterSeconds"] == 400 * 86400
