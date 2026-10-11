"""Session-wide test setup.

By default the suite is fully offline: it starts the real FastAPI app (with Claude replaced by a deterministic fake,
see tests/fake_app.py) on a free local port against a throwaway MongoDB database, and drops that database at the
end. Requirements: a MongoDB at SPARKS_TEST_MONGO_URL (default mongodb://127.0.0.1:27017) — e.g.
`docker run -d -p 27017:27017 mongo:7`.

To run the HTTP tests against an already-running backend instead, set SPARKS_TEST_BASE_URL (no trailing /api) plus
SPARKS_TEST_ADMIN_EMAIL / SPARKS_TEST_ADMIN_PASSWORD. Credentials are never stored in the repository.

The IP-layer generation caps are raised for the session (tests create many guest ids from one IP — exactly the
pattern the limiter blocks in production) and restored afterwards. Identity-level limits are untouched.
"""
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parent.parent
RAISED = {"ip_hourly_cap": 100000, "ip_daily_cap": 100000, "guest_ids_per_ip_daily": 100000, "auth_login_ip_hourly": 100000, "auth_login_email_hourly": 100000, "auth_signup_ip_hourly": 100000, "auth_social_ip_hourly": 100000}
_state: dict = {}

# In-process unit tests import `server`, which connects to Mongo at import time — configure before any test module loads.
os.environ.setdefault("MONGO_URL", os.environ.get("SPARKS_TEST_MONGO_URL", "mongodb://127.0.0.1:27017"))
os.environ.setdefault("DB_NAME", f"sparks_test_{uuid.uuid4().hex[:8]}")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-" + uuid.uuid4().hex)
os.environ.setdefault("SPARKS_TEST_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("SPARKS_TEST_ADMIN_PASSWORD", "local-test-admin-" + uuid.uuid4().hex[:12])
os.environ.setdefault("ADMIN_EMAIL", os.environ["SPARKS_TEST_ADMIN_EMAIL"])
os.environ.setdefault("ADMIN_PASSWORD", os.environ["SPARKS_TEST_ADMIN_PASSWORD"])
os.environ.setdefault("REVENUECAT_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("REVENUECAT_ENVIRONMENT", "SANDBOX")
os.environ.setdefault("APPLE_AUDIENCES", "com.test.datespark")
os.environ.setdefault("GOOGLE_CLIENT_IDS", "test-google-client.apps.googleusercontent.com")
os.environ.setdefault("EMAIL_PROVIDER", "outbox")  # verification / reset mail is stored in Mongo, never sent
sys.path.insert(0, str(BACKEND))


def rebind_server_db() -> None:
    """Motor clients are bound to the event loop they first ran on. In-process tests that start their own loop
    (TestClient) call this so the app's store objects get a fresh client on the new loop."""
    import server
    from motor.motor_asyncio import AsyncIOMotorClient

    server.client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    server.db = server.client[os.environ["DB_NAME"]]
    for holder in (server.route_cache, server.limiter, server.entitlements, server.codes, server.mailer):
        holder.db = server.db


def _is_worker(config) -> bool:
    return hasattr(config, "workerinput")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_local_server() -> None:
    port = _free_port()
    log = open(BACKEND / "tests" / ".server.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.fake_app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND, env={**os.environ, "PYTHONPATH": str(BACKEND)}, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError(f"test server exited early — see {log.name}")
        try:
            if requests.get(f"{base}/api/", timeout=1).ok:
                break
        except requests.RequestException:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("test server did not start")
    _state["proc"] = proc
    os.environ["SPARKS_TEST_BASE_URL"] = base


# Start the server at import time so module-level `os.environ["SPARKS_TEST_BASE_URL"]` lookups in test files resolve.
if "SPARKS_TEST_BASE_URL" not in os.environ and not os.environ.get("PYTEST_XDIST_WORKER"):
    _start_local_server()
API = os.environ["SPARKS_TEST_BASE_URL"].rstrip("/") + "/api"


def _headers():
    admin = {"email": os.environ["SPARKS_TEST_ADMIN_EMAIL"], "password": os.environ["SPARKS_TEST_ADMIN_PASSWORD"]}
    tok = requests.post(f"{API}/auth/login", json=admin, timeout=20).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def pytest_sessionstart(session):
    if _is_worker(session.config):
        return
    try:
        h = _headers()
        _state["before"] = requests.get(f"{API}/admin/config", headers=h, timeout=20).json().get("limits", {})
        requests.put(f"{API}/admin/config", headers=h, json={"limits": RAISED}, timeout=20)
    except Exception:  # backend unreachable — the tests will report it themselves
        _state.pop("before", None)


def pytest_sessionfinish(session, exitstatus):
    if _is_worker(session.config):
        return
    if "before" in _state and "proc" not in _state:
        restore = {k: _state["before"][k] for k in RAISED if k in _state["before"]}
        if restore:
            requests.put(f"{API}/admin/config", headers=_headers(), json={"limits": restore}, timeout=20)
    proc = _state.pop("proc", None)
    if proc:
        proc.terminate()
        proc.wait(timeout=10)
        from pymongo import MongoClient

        MongoClient(os.environ["MONGO_URL"]).drop_database(os.environ["DB_NAME"])
