"""Increment 5 · Phase 1 — Venue Reliability (opening-hours verification).

Unit coverage of hours.py (open / closed / temporarily & permanently closed / overnight / 24-hour / missing hours /
venue time zone / no date / beyond Google's 7-day current-hours window), engine wiring with the LLM mocked
(flag ON vs OFF, closed-venue filtering that never empties the list, Places failure), and API checks for the
`venue_hours` flag, legacy sparks and locked-surprise recipient privacy.
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import recommend  # noqa: E402
from hours import evaluate_hours, hours_on_day, summarize, visit_window  # noqa: E402
from places import _normalize  # noqa: E402
from server import DEFAULT_CONFIG, OUTPUT_FIELDS, GenerateIn, redact_for_recipient  # noqa: E402

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vibe-finder-75.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
AUSTIN = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
ADMIN = {"email": "admin@datespark.app", "password": "SparkAdmin2026!"}
CT = -300  # Austin in June (CDT) = UTC-5

# Saturday 2026-06-27 19:00 CDT == 2026-06-28T00:00Z. "now" is the Wednesday before → inside Google's 7-day window.
PLAN = datetime(2026, 6, 28, 0, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 6, 24, 15, 0, tzinfo=timezone.utc)
FAR = datetime(2026, 7, 25, 23, 0, tzinfo=timezone.utc)  # Saturday 6 PM CDT, 4+ weeks out


def period(open_day, oh, om, close_day, ch, cm, date_open=None, date_close=None):
    o = {"day": open_day, "hour": oh, "minute": om}
    c = {"day": close_day, "hour": ch, "minute": cm}
    if date_open:
        o["date"] = {"year": date_open[0], "month": date_open[1], "day": date_open[2]}
    if date_close:
        c["date"] = {"year": date_close[0], "month": date_close[1], "day": date_close[2]}
    return {"open": o, "close": c}


# Typical restaurant: Tue–Sun 5 PM–11 PM (closed Monday); Sat 27 June is day 6.
REGULAR = [period(d, 17, 0, d, 23, 0) for d in (0, 2, 3, 4, 5, 6)]
CURRENT = [period(d, 17, 0, d, 23, 0, (2026, 6, 24 + i), (2026, 6, 24 + i)) for i, d in enumerate((3, 4, 5, 6))] + [period(0, 17, 0, 0, 23, 0, (2026, 6, 28), (2026, 6, 28))]


def venue(**kw):
    base = {"id": "v1", "business_status": "OPERATIONAL", "utc_offset_minutes": CT, "periods": REGULAR, "current_periods": CURRENT}
    base.update(kw)
    return base


# ---------------------------------------------------------------- unit: hours.py
def test_open_confirmed_from_current_hours():
    r = evaluate_hours(venue(), PLAN, "7:00 PM", "8:30 PM", now_utc=NOW)
    assert r["status"] == "open" and r["confidence"] == "confirmed" and r["source"] == "google_places"
    assert r["detail"].startswith("Open at 7:00 PM") and "closes 11:00 PM" in r["detail"] and r["closes_before_end"] is False
    assert "Regular hours" not in r["detail"]  # confirmed data is not hedged


def test_closed_before_opening_and_stop_running_past_close():
    r = evaluate_hours(venue(), PLAN, "3:00 PM", "4:00 PM", now_utc=NOW)
    assert r["status"] == "closed" and r["confidence"] == "confirmed" and "opens 5:00 PM" in r["detail"]
    late = evaluate_hours(venue(), PLAN, "10:30 PM", "11:45 PM", now_utc=NOW)
    assert late["status"] == "open" and late["closes_before_end"] is True and "before this stop ends" in late["detail"]


def test_closed_all_day_monday_regular():
    monday = datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc)  # Mon 2026-07-06 7 PM CDT, beyond current window
    r = evaluate_hours(venue(), monday, "7:00 PM", None, now_utc=NOW)
    assert r["status"] == "closed" and r["confidence"] == "regular" and "closed at that time" in r["detail"] and "Regular hours — confirm closer to the date" in r["detail"]


def test_temporarily_and_permanently_closed_win_over_hours():
    assert evaluate_hours(venue(business_status="CLOSED_TEMPORARILY"), PLAN, "7:00 PM", None)["status"] == "closed_temporarily"
    perm = evaluate_hours(venue(business_status="CLOSED_PERMANENTLY"), PLAN, "7:00 PM", None)
    assert perm["status"] == "closed_permanently" and perm["confidence"] == "confirmed" and perm["detail"] == "Permanently closed"


def test_overnight_hours_cover_after_midnight_stop():
    bar = venue(periods=[period(d, 18, 0, (d + 1) % 7, 2, 0) for d in range(7)], current_periods=None)
    # 1:00 AM reads earlier than the 7 PM plan start → treated as the following night, still inside Sat 6 PM–Sun 2 AM
    r = evaluate_hours(bar, PLAN, "1:00 AM", "1:45 AM", now_utc=NOW)
    assert r["status"] == "open" and r["confidence"] == "regular" and r["checked_for"].startswith("2026-06-28T01:00")
    assert evaluate_hours(bar, PLAN, "3:00 AM", None, now_utc=NOW)["status"] == "closed"


def test_twenty_four_hour_venue():
    diner = venue(periods=[{"open": {"day": 0, "hour": 0, "minute": 0}}], current_periods=None)
    r = evaluate_hours(diner, FAR, "4:00 AM", None, now_utc=NOW)
    assert r["status"] == "open" and "Open 24 hours" in r["detail"] and r["confidence"] == "regular"
    assert hours_on_day(diner, FAR, now_utc=NOW)["text"].endswith("open 24 hours")


def test_missing_hours_is_unverified_not_closed():
    r = evaluate_hours(venue(periods=None, current_periods=None), PLAN, "7:00 PM", None, now_utc=NOW)
    assert r["status"] == "unknown" and r["confidence"] == "none" and r["detail"] == "Hours not verified"
    assert evaluate_hours(None, PLAN, "7:00 PM", None)["status"] == "unknown"  # no matched venue
    assert hours_on_day(venue(periods=[], current_periods=[]), PLAN, now_utc=NOW) == {"text": "Unknown", "confidence": "none"}


def test_no_plan_date_is_unverified():
    r = evaluate_hours(venue(), None, "7:00 PM", None)
    assert r["status"] == "unknown" and "no date chosen" in r["detail"]
    assert hours_on_day(venue(), None)["confidence"] == "none"


def test_venue_timezone_drives_the_evaluation():
    # Same UTC instant: 00:00Z = 7 PM in Austin (open) but 8 PM in New York (open) and 5 PM in Los Angeles (open)...
    # ...and for a venue in London (UTC+1) it is 1 AM Sunday → closed. The user's own time zone is irrelevant.
    london = venue(utc_offset_minutes=60, current_periods=None)
    r = evaluate_hours(london, PLAN, None, None, now_utc=NOW)  # no stop clock → evaluate at the plan instant
    assert r["status"] == "closed" and r["checked_for"].startswith("2026-06-28T01:00")
    assert evaluate_hours(venue(utc_offset_minutes=None), PLAN, "7:00 PM", None)["detail"].endswith("venue time zone unavailable")


def test_beyond_current_window_uses_regular_hours_with_caveat():
    r = evaluate_hours(venue(), FAR, "6:00 PM", "7:00 PM", now_utc=NOW)
    assert r["status"] == "open" and r["confidence"] == "regular" and "Regular hours — confirm closer to the date" in r["detail"]
    # current-hours window present but the visit date is outside its covered dates → regular, never 'confirmed'
    hint = hours_on_day(venue(), FAR, now_utc=NOW)
    assert hint["confidence"] == "regular" and hint["text"].startswith("Sat ")


def test_visit_window_and_summary_helpers():
    local = datetime(2026, 6, 27, 19, 0)
    s, e = visit_window(local, "9:00 PM", None)
    assert (s.hour, (e - s).seconds // 60) == (21, 60)
    s, e = visit_window(local, "11:30 PM", "12:30 AM")
    assert e.day == 28 and e.hour == 0
    acts = [{"hours_status": {"status": "open", "confidence": "confirmed"}}, {"hours_status": {"status": "open", "confidence": "regular"}}, {"hours_status": {"status": "closed"}}, {}]
    assert summarize(acts) == {"confirmed_open": 1, "regular_open": 1, "closed": 1, "unverified": 1}


def test_when_text_uses_venue_area_local_time():
    # 7 PM Saturday in Austin is 00:00Z Sunday — the model must hear "Saturday 7:00 PM", not "Sunday 12:00 AM".
    assert recommend.when_text("2026-06-28T00:00:00Z", None, None, CT).startswith("Saturday June 27, 7:00 PM local time")
    assert recommend.when_text("2026-06-28T00:00:00Z", None, None, None).startswith("Sunday June 28, 12:00 AM")  # legacy UTC path when no venues


def test_places_normalize_exposes_structured_hours():
    raw = {"id": "p1", "displayName": {"text": "Cafe"}, "location": {"latitude": 30.27, "longitude": -97.74}, "businessStatus": "OPERATIONAL", "utcOffsetMinutes": CT,
           "regularOpeningHours": {"weekdayDescriptions": ["Mon: Closed"], "periods": REGULAR}, "currentOpeningHours": {"periods": CURRENT}}
    v = _normalize(raw, 30.2672, -97.7431)
    assert v["hours"] == ["Mon: Closed"] and v["periods"] == REGULAR and v["current_periods"] == CURRENT
    assert v["business_status"] == "OPERATIONAL" and v["utc_offset_minutes"] == CT
    bare = _normalize({"id": "p2", "displayName": {"text": "X"}}, 30.0, -97.0)
    assert bare["periods"] is None and bare["business_status"] is None and bare["utc_offset_minutes"] is None


# ---------------------------------------------------------------- engine wiring (LLM + Places mocked)
VENUES = [
    {**venue(id="open1"), "name": "Open Bistro", "address": "1 Main", "lat": 30.2672, "lng": -97.7431, "rating": 4.5, "hours": ["Sat: 5–11 PM"], "maps_url": None, "distance_miles": 0.2, "types": ["restaurant"]},
    {**venue(id="gone", business_status="CLOSED_PERMANENTLY"), "name": "Gone Grill", "address": "2 Main", "lat": 30.27, "lng": -97.74, "rating": 4.0, "hours": None, "maps_url": None, "distance_miles": 0.4, "types": ["restaurant"]},
    {**venue(id="nohours", periods=None, current_periods=None), "name": "Mystery Bar", "address": "3 Main", "lat": 30.28, "lng": -97.74, "rating": 4.2, "hours": None, "maps_url": None, "distance_miles": 0.9, "types": ["bar"]},
]
REPLY = json.dumps({"sparks": [{"title": "T", "emoji": "✨", "tagline": "a → b", "description": "d", "primary_vibe": "Fun", "vibe_tags": [], "estimated_cost": "$40", "estimated_duration": "2 hours", "why": "w",
                               "activities": [{"name": "Dinner", "venue_id": "open1", "start_time": "7:00 PM", "end_time": "8:30 PM", "estimated_cost": "$30"},
                                              {"name": "Drinks", "venue_id": "nohours", "start_time": "9:00 PM", "end_time": "10:00 PM", "estimated_cost": "$10"},
                                              {"name": "Walk", "venue_id": None, "start_time": "10:00 PM", "end_time": "10:30 PM", "estimated_cost": "Free"}]}]})


class _Cap:
    system = prompt = None


class _FakeChat:
    def __init__(self, api_key, session_id, system_message):
        _Cap.system = system_message

    def with_model(self, *_):
        return self

    async def send_message(self, msg):
        _Cap.prompt = msg.text
        return REPLY


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(recommend, "LlmChat", _FakeChat)
    monkeypatch.setenv("EMERGENT_LLM_KEY", "test")

    def run(body: dict, venues=VENUES, venue_hours=True):
        async def fake_gather(*_):
            return [dict(v) for v in venues]

        monkeypatch.setattr(recommend, "gather_venues", fake_gather)
        g = GenerateIn(**body)
        sparks = asyncio.run(recommend.generate_sparks(relationship_type=g.relationship_type, vibes=g.vibes, budget=g.budget, distance=g.distance, location=g.location, exclude_titles=[], history={},
                                                       date_label=None, time_label=None, ai_settings={}, occasion=None, surprise=False, experience=g.experience_context(), venue_hours=venue_hours))
        venues_sent = json.loads(_Cap.prompt.split("venue_id only):\n", 1)[1].split("\n\n", 1)[0])
        ctx = json.loads(_Cap.prompt.split("CONTEXT:\n", 1)[1].split("\n\nVENUES", 1)[0])
        return sparks[0], venues_sent, ctx

    return run


BODY = {"relationship_type": "friends", "vibes": ["fun"], "budget": "25-50", "distance": "10", "location": AUSTIN, "scheduled_at": "2026-06-28T00:00:00Z"}


def test_flag_on_filters_closed_hints_model_and_stamps_stops(engine):
    sp, sent, ctx = engine(BODY)
    assert ctx["when"].startswith("Saturday June 27, 7:00 PM local time")  # venue offset applied
    assert [v["venue_id"] for v in sent] == ["open1", "nohours"]  # permanently closed venue never shown to the model
    assert sent[0]["hours_on_plan_day"].startswith("Sat ") and sent[1]["hours_on_plan_day"] == "Unknown"
    assert "hours_on_plan_day" in _Cap.system
    st = [a["hours_status"]["status"] for a in sp["activities"]]
    assert st == ["open", "unknown", "unknown"]
    assert sp["activities"][0]["hours_status"]["confidence"] in ("confirmed", "regular")
    assert sp["hours_summary"]["closed"] == 0 and sp["hours_summary"]["unverified"] == 2
    assert sp["hours_summary"]["confirmed_open"] + sp["hours_summary"]["regular_open"] == 1


def test_flag_off_is_byte_identical_legacy_behaviour(engine):
    sp, sent, _ = engine(BODY, venue_hours=False)
    assert [v["venue_id"] for v in sent] == ["open1", "gone", "nohours"] and "hours_on_plan_day" not in sent[0]
    assert _Cap.system == recommend.SYSTEM_PROMPT
    assert "hours_summary" not in sp and all("hours_status" not in a for a in sp["activities"])


def test_all_venues_closed_does_not_empty_recommendations(engine):
    closed_only = [dict(VENUES[1]), {**VENUES[1], "id": "gone2"}]
    _, sent, _ = engine(BODY, venues=closed_only)
    assert len(sent) == 2  # keeps the originals rather than returning nothing


def test_places_failure_still_generates_with_unverified_hours(engine):
    sp, sent, _ = engine(BODY, venues=[])
    assert sent == [] and len(sp["activities"]) == 3
    assert all(a["hours_status"] == {"status": "unknown", "confidence": "none", "detail": "Hours not verified", "source": "google_places"} for a in sp["activities"])
    assert sp["hours_summary"] == {"confirmed_open": 0, "regular_open": 0, "closed": 0, "unverified": 3}


def test_no_scheduled_at_marks_all_unverified(engine):
    sp, _, _ = engine({k: v for k, v in BODY.items() if k != "scheduled_at"})
    assert all(a["hours_status"]["status"] == "unknown" for a in sp["activities"])


# ---------------------------------------------------------------- redaction / legacy / API
def test_locked_recipient_never_sees_hours():
    sp = {"surprise": True, "revealed_steps": 1, "scheduled_at": "2099-01-01T20:00:00Z", "location_label": "Austin",
          "activities": [{"start_time": "7:00 PM", "address": "1 Main", "hours_status": {"status": "open"}}, {"hours_status": {"status": "closed"}}],
          "hours_summary": {"confirmed_open": 1, "regular_open": 0, "closed": 1, "unverified": 0}}
    out = redact_for_recipient(dict(sp))
    assert out["locked_for_recipient"] is True and out["activities"] == [] and out["hours_summary"] is None
    assert "hours_summary" in OUTPUT_FIELDS


def test_legacy_spark_without_hours_fields_is_untouched():
    legacy = {"surprise": False, "activities": [{"activity_name": "Coffee"}]}
    out = redact_for_recipient(dict(legacy))
    assert "hours_summary" not in out and "hours_status" not in out["activities"][0]
    assert DEFAULT_CONFIG["features"]["venue_hours"] is True


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def test_venue_hours_flag_is_public_and_independent(s):
    h = {"Authorization": f"Bearer {s.post(f'{API}/auth/login', json=ADMIN).json()['access_token']}"}
    assert s.get(f"{API}/config/public").json()["features"]["venue_hours"] is True
    try:
        f = s.put(f"{API}/admin/config", headers=h, json={"features": {"venue_hours": False}}).json()["features"]
        assert f["venue_hours"] is False and f["experience_output"] is True and f["experience_builder"] is True and f["experience_profiles"] is True
    finally:
        f = s.put(f"{API}/admin/config", headers=h, json={"features": {"venue_hours": True}}).json()["features"]
        assert f["venue_hours"] is True


def test_live_generation_carries_hours_status(s):
    guest = f"guest-{uuid.uuid4().hex[:12]}"
    body = {"relationship_type": "partner", "vibes": ["foodie"], "budget": "50-100", "distance": "10", "location": AUSTIN, "scheduled_at": "2026-06-28T00:00:00Z"}
    r = s.post(f"{API}/sparks/generate", headers={"X-Guest-ID": guest, "X-Premium": "1"}, json=body, timeout=170)
    assert r.status_code == 200, r.text
    for sp in r.json()["sparks"]:
        assert set(sp["hours_summary"]) == {"confirmed_open", "regular_open", "closed", "unverified"}
        for a in sp["activities"]:
            h = a["hours_status"]
            assert h["status"] in ("open", "closed", "closed_permanently", "closed_temporarily", "unknown") and h["confidence"] in ("confirmed", "regular", "none")
            if not a["verified"]:
                assert h["status"] == "unknown"
            if h["confidence"] == "regular":
                assert "Regular hours — confirm closer to the date" in h["detail"] or "Open 24 hours" in h["detail"]
    shared = s.get(f"{API}/shared/{r.json()['sparks'][0]['id']}").json()
    assert shared["hours_summary"] is not None and "hours_status" in shared["activities"][0]
