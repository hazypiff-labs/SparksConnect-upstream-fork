"""Audit 2026-10-10 Wave 4 (backend half) — invitation web page and app-link association files."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import server
from conftest import rebind_server_db


@pytest.fixture(scope="module")
def c():
    rebind_server_db()
    with TestClient(server.app) as client:
        yield client


def insert(c, **fields):
    sid = str(uuid.uuid4())
    doc = {"id": sid, "owner_type": "guest", "owner_id": "g-owner", "title": "Plan", "emoji": "✨", "tagline": "t", "description": "d",
           "activities": [{"activity_name": "Secret dinner", "venue": "Hidden Bistro", "address": "1 Secret St", "start_time": "7:00 PM"},
                          {"activity_name": "Secret show", "venue": "Club", "address": "2 Secret St", "start_time": "9:00 PM"}],
           "surprise": False, "revealed_steps": 2, "location": {"label": "Owner Home", "lat": 1.0, "lng": 2.0}, "created_at": datetime.now(timezone.utc)}
    doc.update(fields)
    c.portal.call(lambda: server.db.sparks.insert_one(doc))
    return sid


def test_invite_page_escapes_model_text(c):
    sid = insert(c, title='<script>alert("x")</script>', tagline="<img src=x onerror=alert(1)>")
    r = c.get(f"/s/{sid}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "<script>alert" not in r.text and "&lt;script&gt;" in r.text and "<img src=x" not in r.text
    assert "Owner Home" not in r.text  # never the owner's location
    assert f"datespark://spark/{sid}" in r.text


def test_invite_page_respects_surprise_lock(c):
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    sid = insert(c, surprise=True, revealed_steps=1, fully_revealed_at=None, scheduled_at=future)
    r = c.get(f"/s/{sid}")
    assert "Secret show" not in r.text and "Club" not in r.text
    assert "1 Secret St" in r.text  # only where to meet


def test_invite_page_404(c):
    assert c.get(f"/s/{uuid.uuid4()}").status_code == 404


def test_app_link_files(c, monkeypatch):
    assert c.get("/.well-known/apple-app-site-association").status_code == 404
    assert c.get("/.well-known/assetlinks.json").status_code == 404
    monkeypatch.setenv("APPLE_APP_ID", "TEAMID.com.example.datespark")
    monkeypatch.setenv("ANDROID_PACKAGE", "com.example.datespark")
    monkeypatch.setenv("ANDROID_SHA256_FINGERPRINTS", "AA:BB")
    aasa = c.get("/.well-known/apple-app-site-association").json()
    assert aasa["applinks"]["details"][0]["appIDs"] == ["TEAMID.com.example.datespark"]
    assert c.get("/.well-known/assetlinks.json").json()[0]["target"]["package_name"] == "com.example.datespark"


def test_healthz(c):
    assert c.get("/api/healthz").json() == {"ok": True}
