"""Real travel routing (Increment 5 · Phase 2) — provider abstraction with cache, daily cap and safe fallback.

Provider: Google Routes API `computeRoutes` (SKU "Compute Routes Essentials"). Requests deliberately avoid every
Pro/Enterprise trigger (no routingPreference, no optimizeWaypointOrder, ≤10 intermediates, no modifiers).

Contract: `route_legs()` returns {leg_index: leg} for the legs it could route. Anything it cannot route — no key,
API not enabled (403), quota (429), timeout, no route (transit gaps), daily cap reached — is simply absent so the
caller keeps the existing straight-line estimate for that leg. This module never raises into generation.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger("routing")

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.legs.distanceMeters,routes.legs.duration"  # Essentials-tier fields only
MODES = {"drive": "DRIVE", "walk": "WALK", "transit": "TRANSIT"}
CACHE_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_DAILY_LIMIT = 300  # hard stop well inside the 10,000/month free tier
SOURCE = "google_routes"
MODE_LABEL = {"walk": "Walk", "transit": "Transit", "drive": "Drive"}


def routing_key() -> str:
    return os.environ.get("GOOGLE_ROUTES_API_KEY") or os.environ.get("GOOGLE_PLACES_API_KEY") or ""


def daily_limit() -> int:
    try:
        return int(os.environ.get("ROUTES_DAILY_LIMIT", DEFAULT_DAILY_LIMIT))
    except ValueError:
        return DEFAULT_DAILY_LIMIT


class RouteCache:
    """Mongo-backed cache + daily usage counter. Any DB hiccup degrades to 'no cache', never to an error."""

    def __init__(self, db: Any):
        self.db = db

    async def ensure_indexes(self) -> None:
        await self.db.route_cache.create_index("created_at", expireAfterSeconds=CACHE_TTL_SECONDS)
        await self.db.route_cache.create_index("key", unique=True)
        await self.db.route_usage.create_index("day", unique=True)

    async def get(self, key: str) -> dict | None:
        try:
            doc = await self.db.route_cache.find_one({"key": key}, {"_id": 0, "leg": 1})
            return doc["leg"] if doc else None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("route cache read failed: %s", exc)
            return None

    async def put(self, key: str, leg: dict) -> None:
        try:
            await self.db.route_cache.update_one({"key": key}, {"$set": {"leg": leg, "created_at": datetime.now(timezone.utc)}}, upsert=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("route cache write failed: %s", exc)

    async def reserve_call(self) -> bool:
        """Count one provider call against today's cap. False when the cap is reached (caller must fall back)."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            doc = await self.db.route_usage.find_one_and_update({"day": day}, {"$inc": {"calls": 1}}, upsert=True, return_document=True)
            return int(doc.get("calls", 0)) <= daily_limit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("route usage counter failed: %s", exc)
            return False


def _cache_key(a: dict, b: dict, mode: str, departure: str | None) -> str:
    ida = a.get("venue_id") or f"{a.get('lat')},{a.get('lng')}"
    idb = b.get("venue_id") or f"{b.get('lat')},{b.get('lng')}"
    bucket = (departure or "")[:13] if mode == "transit" else ""  # transit varies by hour; road/walk do not
    return f"{ida}|{idb}|{mode}|{bucket}"


def _leg(index: int, meters: float, seconds: float, mode: str) -> dict:
    miles = round(meters / 1609.34, 2)
    minutes = max(1, int(round(seconds / 60)))
    return {"from_index": index, "to_index": index + 1, "miles": miles, "minutes": minutes, "mode": mode, "source": SOURCE, "estimate": False,
            "label": f"{MODE_LABEL[mode]} · {minutes} min · {miles} mi · via Google Routes"}


def _parse_duration(text: str | None) -> float | None:
    if not text or not str(text).endswith("s"):
        return None
    try:
        return float(str(text)[:-1])
    except ValueError:
        return None


async def _post(body: dict) -> tuple[int, dict]:
    """Single HTTP call — isolated so tests can stub it. Returns (status, json)."""
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.post(ROUTES_URL, json=body, headers={"Content-Type": "application/json", "X-Goog-Api-Key": routing_key(), "X-Goog-FieldMask": FIELD_MASK})
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {}


def _waypoint(stop: dict) -> dict:
    return {"location": {"latLng": {"latitude": stop["lat"], "longitude": stop["lng"]}}}


async def _compute(stops: list[dict], mode: str, departure: str | None) -> list[tuple[float, float]] | None:
    """Legs (meters, seconds) between consecutive stops in one request. None when the provider cannot answer."""
    body: dict[str, Any] = {"origin": _waypoint(stops[0]), "destination": _waypoint(stops[-1]), "travelMode": MODES[mode], "units": "IMPERIAL"}
    if len(stops) > 2:
        body["intermediates"] = [_waypoint(s) for s in stops[1:-1]]
    if departure and mode == "transit":
        body["departureTime"] = departure
    try:
        status, data = await _post(body)
    except Exception as exc:  # timeouts, DNS, connection resets
        logger.warning("Routes request failed: %s", type(exc).__name__)
        return None
    if status == 403:
        logger.warning("Routes API not authorised for this key/project (403) — using straight-line estimates")
        return None
    if status == 429:
        logger.warning("Routes API quota/rate limit (429) — using straight-line estimates")
        return None
    if status >= 400:
        logger.warning("Routes API error %s — using straight-line estimates", status)
        return None
    routes = data.get("routes") or []
    legs = (routes[0].get("legs") if routes else None) or []
    if len(legs) != len(stops) - 1:
        return None
    out = []
    for leg in legs:
        secs = _parse_duration(leg.get("duration"))
        meters = leg.get("distanceMeters")
        if secs is None or meters is None:
            return None
        out.append((float(meters), secs))
    return out


async def route_legs(activities: list[dict], transport: str | None, departure: str | None, cache: RouteCache | None) -> dict[int, dict]:
    """Provider-routed legs keyed by from_index. Only consecutive stops that both have coordinates are considered."""
    mode = (transport or "drive").lower()
    if mode not in MODES or not routing_key():
        return {}
    pairs = [(i, activities[i], activities[i + 1]) for i in range(len(activities) - 1)
             if None not in (activities[i].get("lat"), activities[i].get("lng"), activities[i + 1].get("lat"), activities[i + 1].get("lng"))]
    if not pairs:
        return {}
    result: dict[int, dict] = {}
    todo: list[tuple[int, dict, dict]] = []
    for i, a, b in pairs:
        cached = await cache.get(_cache_key(a, b, mode, departure)) if cache else None
        if cached:
            result[i] = {**cached, "from_index": i, "to_index": i + 1}
        else:
            todo.append((i, a, b))
    if not todo:
        return result

    async def fetch(stops: list[dict], indices: list[int]) -> None:
        if cache and not await cache.reserve_call():
            logger.warning("Routes daily cap reached — using straight-line estimates")
            return
        computed = await _compute(stops, mode, departure)
        if not computed:
            return
        for idx, (meters, secs) in zip(indices, computed):
            leg = _leg(idx, meters, secs, mode)
            result[idx] = leg
            if cache:
                await cache.put(_cache_key(activities[idx], activities[idx + 1], mode, departure), leg)

    # Consecutive uncached pairs can share one request (intermediates) — except transit, which routes leg by leg.
    if mode == "transit":
        for i, a, b in todo:
            await fetch([a, b], [i])
    else:
        run: list[tuple[int, dict, dict]] = []
        for item in todo:
            if run and item[0] != run[-1][0] + 1:
                await fetch([run[0][1]] + [x[2] for x in run], [x[0] for x in run])
                run = []
            run.append(item)
        if run:
            await fetch([run[0][1]] + [x[2] for x in run], [x[0] for x in run])
    return result


def routing_source(legs: list[dict]) -> str | None:
    """Spark-level summary: google_routes | mixed | straight_line | None (no legs)."""
    if not legs:
        return None
    routed = sum(1 for l in legs if l.get("source") == SOURCE)
    return SOURCE if routed == len(legs) else "mixed" if routed else "straight_line"


def within_days(iso: str | None, days: int = 7) -> bool:
    """Transit timetables are only meaningful near the departure; beyond that we route without departureTime."""
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return False
    return timedelta(0) <= dt - datetime.now(timezone.utc) <= timedelta(days=days)
