"""Session-wide test setup.

The live tests create a fresh guest id per test from ONE egress IP. In production that pattern is exactly what the
Phase A limiter blocks (guest-id rotation), so for the duration of a test session the IP-layer caps are raised
through the admin API and restored afterwards. Identity-level limits (free quota, premium ceilings) are untouched —
tests that need tight values set and restore their own. Runs on the xdist controller only (never in workers), so a
fast-finishing worker cannot re-tighten limits while others are still running.
"""
import os

import requests

API = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vibe-finder-75.preview.emergentagent.com").rstrip("/") + "/api"
ADMIN = {"email": "admin@datespark.app", "password": "SparkAdmin2026!"}
RAISED = {"ip_hourly_cap": 100000, "ip_daily_cap": 100000, "guest_ids_per_ip_daily": 100000}
_state: dict = {}


def _is_worker(config) -> bool:
    return hasattr(config, "workerinput")


def _headers():
    tok = requests.post(f"{API}/auth/login", json=ADMIN, timeout=20).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def pytest_sessionstart(session):
    if _is_worker(session.config):
        return
    try:
        h = _headers()
        _state["before"] = requests.get(f"{API}/admin/config", headers=h, timeout=20).json().get("limits", {})
        requests.put(f"{API}/admin/config", headers=h, json={"limits": RAISED}, timeout=20)
    except Exception:  # backend unreachable — the tests will report it themselves
        _state.clear()


def pytest_sessionfinish(session, exitstatus):
    if _is_worker(session.config) or "before" not in _state:
        return
    restore = {k: _state["before"][k] for k in RAISED if k in _state["before"]}
    if restore:
        requests.put(f"{API}/admin/config", headers=_headers(), json={"limits": restore}, timeout=20)
