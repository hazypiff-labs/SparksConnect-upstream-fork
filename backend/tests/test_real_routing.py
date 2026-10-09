"""Increment 5 · Phase 2 — Real travel routing (provider abstraction, cache, daily cap, fallback).

All provider traffic is stubbed at `routing._post` — this suite never contacts Google Routes and never incurs
charges. The `real_routing` flag is OFF by default and the live checks assert that production output still
carries straight-line legs only.
"""
import asyncio
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import routing  # noqa: E402
from recommend import compute_travel_legs, resolve_travel_legs  # noqa: E402
from server import DEFAULT_CONFIG, OUTPUT_FIELDS, redact_for_recipient  # noqa: E402

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vibe-finder-75.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
ADMIN = {"email": "admin@datespark.app", "password": "SparkAdmin2026!"}

STOPS = [
    {"activity_name": "Coffee", "venue_id": "a", "lat": 30.2672, "lng": -97.7431},
    {"activity_name": "Park", "venue_id": "b", "lat": 30.2750, "lng": -97.7400},
    {"activity_name": "Dessert", "venue_id": "c", "lat": 30.2800, "lng": -97.7450},
]


class MemCache(routing.RouteCache):
    """In-memory stand-in for the Mongo cache with the same contract."""

    def __init__(self, limit=1000):
        self.store, self.calls, self.limit = {}, 0, limit

    async def get(self, key):
        return self.store.get(key)

    async def put(self, key, leg):
        self.store[key] = leg

    async def reserve_call(self):
        self.calls += 1
        return self.calls <= self.limit


class Provider:
    """Scripted `_post` replacement: records request bodies, replays queued responses."""

    def __init__(self, *responses):
        self.responses, self.bodies = list(responses), []

    async def __call__(self, body):
        self.bodies.append(body)
        r = self.responses.pop(0) if self.responses else (200, {})
        if isinstance(r, Exception):
            raise r
        return r


def ok(*legs):
    return 200, {"routes": [{"legs": [{"distanceMeters": m, "duration": f"{s}s"} for m, s in legs]}]}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ROUTES_DAILY_LIMIT", "300")


# ---------------------------------------------------------------- straight-line legs now self-describe
def test_straight_line_legs_are_labelled_estimates():
    legs = compute_travel_legs(STOPS, "walk")
    assert len(legs) == 2 and all(l["source"] == "straight_line" and l["estimate"] is True for l in legs)
    assert "via Google Routes" not in legs[0]["label"]
    assert routing.routing_source(legs) == "straight_line" and routing.routing_source([]) is None


def test_flag_off_never_calls_provider(key, monkeypatch):
    p = Provider(ok((900, 600), (800, 500)))
    monkeypatch.setattr(routing, "_post", p)
    legs = run(resolve_travel_legs(STOPS, "drive", None, real_routing=False, route_cache=MemCache()))
    assert p.bodies == [] and all(l["source"] == "straight_line" for l in legs)


# ---------------------------------------------------------------- supported modes
@pytest.mark.parametrize("mode,api_mode", [("drive", "DRIVE"), ("walk", "WALK")])
def test_drive_and_walk_route_all_legs_in_one_request(key, monkeypatch, mode, api_mode):
    p = Provider(ok((1609, 300), (3218, 900)))
    monkeypatch.setattr(routing, "_post", p)
    cache = MemCache()
    legs = run(resolve_travel_legs(STOPS, mode, None, True, cache))
    assert len(p.bodies) == 1 and cache.calls == 1
    body = p.bodies[0]
    assert body["travelMode"] == api_mode and len(body["intermediates"]) == 1
    assert "routingPreference" not in body and "optimizeWaypointOrder" not in body  # stays on the Essentials SKU
    assert [(l["miles"], l["minutes"], l["source"], l["estimate"]) for l in legs] == [(1.0, 5, "google_routes", False), (2.0, 15, "google_routes", False)]
    assert legs[0]["mode"] == mode and "via Google Routes" in legs[0]["label"]
    assert routing.routing_source(legs) == "google_routes"


def test_transit_routes_leg_by_leg_with_departure_time(key, monkeypatch):
    p = Provider(ok((1200, 480)), ok((2500, 900)))
    monkeypatch.setattr(routing, "_post", p)
    cache = MemCache()
    legs = run(routing.route_legs(STOPS, "transit", "2026-06-28T00:00:00Z", cache))
    assert len(p.bodies) == 2 and all(b["travelMode"] == "TRANSIT" and b["departureTime"] == "2026-06-28T00:00:00Z" and "intermediates" not in b for b in p.bodies)
    assert sorted(legs) == [0, 1] and legs[1]["minutes"] == 15


def test_far_future_transit_omits_departure_time(key, monkeypatch):
    p = Provider(ok((1200, 480)), ok((2500, 900)))
    monkeypatch.setattr(routing, "_post", p)
    run(resolve_travel_legs(STOPS, "transit", "2099-01-01T01:00:00Z", True, MemCache()))
    assert all("departureTime" not in b for b in p.bodies)


# ---------------------------------------------------------------- cache
def test_cache_hit_avoids_second_provider_call(key, monkeypatch):
    p = Provider(ok((1609, 300), (3218, 900)))
    monkeypatch.setattr(routing, "_post", p)
    cache = MemCache()
    first = run(resolve_travel_legs(STOPS, "drive", None, True, cache))
    second = run(resolve_travel_legs(STOPS, "drive", None, True, cache))
    assert len(p.bodies) == 1 and cache.calls == 1 and first == second
    assert len(cache.store) == 2 and all("|drive|" in k for k in cache.store)


def test_partial_cache_only_fetches_missing_leg(key, monkeypatch):
    cache = MemCache()
    run(cache.put(routing._cache_key(STOPS[0], STOPS[1], "drive", None), routing._leg(0, 1609, 300, "drive")))
    p = Provider(ok((3218, 900)))
    monkeypatch.setattr(routing, "_post", p)
    legs = run(resolve_travel_legs(STOPS, "drive", None, True, cache))
    assert len(p.bodies) == 1 and "intermediates" not in p.bodies[0]  # single leg b→c
    assert [l["source"] for l in legs] == ["google_routes", "google_routes"]


# ---------------------------------------------------------------- failures → straight-line fallback, still labelled
@pytest.mark.parametrize("response,reason", [((403, {"error": {"status": "PERMISSION_DENIED"}}), "api not enabled / key restricted"),
                                             ((429, {"error": {"status": "RESOURCE_EXHAUSTED"}}), "quota or rate limit"),
                                             ((500, {}), "server error"),
                                             ((200, {"routes": []}), "no route found"),
                                             ((200, {"routes": [{"legs": [{"distanceMeters": 1}]}]}), "malformed leg count"),
                                             (__import__("httpx").ReadTimeout("timeout"), "timeout")])
def test_provider_failures_fall_back_to_straight_line(key, monkeypatch, response, reason):
    monkeypatch.setattr(routing, "_post", Provider(response))
    legs = run(resolve_travel_legs(STOPS, "drive", None, True, MemCache()))
    assert len(legs) == 2 and all(l["source"] == "straight_line" and l["estimate"] is True for l in legs), reason
    assert routing.routing_source(legs) == "straight_line"


def test_transit_gap_yields_mixed_sources(key, monkeypatch):
    monkeypatch.setattr(routing, "_post", Provider(ok((1200, 480)), (200, {"routes": []})))
    legs = run(resolve_travel_legs(STOPS, "transit", None, True, MemCache()))
    assert [l["source"] for l in legs] == ["google_routes", "straight_line"]
    assert legs[1]["estimate"] is True and "via Google Routes" not in legs[1]["label"]
    assert routing.routing_source(legs) == "mixed"


def test_missing_key_and_unknown_mode_skip_provider(monkeypatch):
    monkeypatch.delenv("GOOGLE_ROUTES_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    p = Provider(ok((1, 1), (1, 1)))
    monkeypatch.setattr(routing, "_post", p)
    assert run(routing.route_legs(STOPS, "drive", None, MemCache())) == {} and p.bodies == []
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "k")
    assert run(routing.route_legs(STOPS, "teleport", None, MemCache())) == {} and p.bodies == []


def test_daily_cap_blocks_provider_calls(key, monkeypatch):
    p = Provider(ok((1609, 300), (3218, 900)))
    monkeypatch.setattr(routing, "_post", p)
    cache = MemCache(limit=0)
    legs = run(resolve_travel_legs(STOPS, "drive", None, True, cache))
    assert p.bodies == [] and all(l["source"] == "straight_line" for l in legs)


def test_stops_without_coordinates_are_skipped(key, monkeypatch):
    p = Provider(ok((1609, 300)))
    monkeypatch.setattr(routing, "_post", p)
    stops = [STOPS[0], {"activity_name": "Walk", "venue_id": None, "lat": None, "lng": None}, STOPS[2]]
    assert run(routing.route_legs(stops, "drive", None, MemCache())) == {} and p.bodies == []


# ---------------------------------------------------------------- compatibility / privacy
def test_legacy_legs_without_source_are_treated_as_straight_line():
    legacy = [{"from_index": 0, "to_index": 1, "miles": 1.0, "minutes": 3, "mode": "drive", "label": "Drive · 3 min · 1.0 mi"}]
    assert routing.routing_source(legacy) == "straight_line"


def test_locked_recipient_loses_routing_source():
    sp = {"surprise": True, "revealed_steps": 1, "scheduled_at": "2099-01-01T20:00:00Z", "activities": [{"start_time": "7:00 PM"}, {}], "location_label": "Austin",
          "travel_legs": [routing._leg(0, 1609, 300, "drive")], "routing_source": "google_routes"}
    out = redact_for_recipient(dict(sp))
    assert out["travel_legs"] == [] and out["routing_source"] is None and "routing_source" in OUTPUT_FIELDS


# ---------------------------------------------------------------- API (flag OFF in production — no provider traffic)
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def test_real_routing_flag_defaults_off_and_is_independent(s):
    assert DEFAULT_CONFIG["features"]["real_routing"] is False
    pub = s.get(f"{API}/config/public").json()["features"]
    assert pub["real_routing"] is False and pub["venue_hours"] is True and pub["experience_output"] is True
    h = {"Authorization": f"Bearer {s.post(f'{API}/auth/login', json=ADMIN).json()['access_token']}"}
    f = s.put(f"{API}/admin/config", headers=h, json={"features": {"venue_hours": False}}).json()["features"]
    assert f["real_routing"] is False and f["venue_hours"] is False  # toggling another flag never switches routing on
    f = s.put(f"{API}/admin/config", headers=h, json={"features": {"venue_hours": True}}).json()["features"]
    assert f["real_routing"] is False and f["venue_hours"] is True


def test_live_generation_stays_straight_line_while_flag_off(s):
    guest = f"guest-{uuid.uuid4().hex[:12]}"
    body = {"relationship_type": "friends", "vibes": ["fun"], "budget": "25-50", "distance": "10", "location": AUSTIN, "experience_type": "friends", "party_size": 3, "transport": "walk"}
    r = s.post(f"{API}/sparks/generate", headers={"X-Guest-ID": guest, "X-Premium": "1"}, json=body, timeout=170)
    assert r.status_code == 200, r.text
    for sp in r.json()["sparks"]:
        assert sp["routing_source"] in (None, "straight_line")
        for leg in sp["travel_legs"]:
            assert leg["source"] == "straight_line" and leg["estimate"] is True and "via Google Routes" not in leg["label"]
