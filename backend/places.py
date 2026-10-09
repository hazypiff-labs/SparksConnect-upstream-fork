"""Location / venue data layer.

Provider-agnostic surface: `search_venues()` and `geocode()`.
Currently backed by Google Places API (New) with OpenStreetMap Nominatim as a
geocoding fallback. Additional providers can be plugged in here later.
"""
import logging
import math
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("places")

PLACES_FIELDS = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.regularOpeningHours,places.priceLevel,places.rating,"
    "places.userRatingCount,places.types,places.googleMapsUri,places.websiteUri,"
    # Venue reliability (Increment 5 · Phase 1). Same SKU tier as regularOpeningHours — no added cost.
    "places.businessStatus,places.currentOpeningHours,places.utcOffsetMinutes"
)

PRICE_LEVEL_LABEL = {
    "PRICE_LEVEL_FREE": "Free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _normalize(place: dict[str, Any], lat: float, lng: float) -> dict[str, Any]:
    loc = place.get("location") or {}
    plat, plng = loc.get("latitude"), loc.get("longitude")
    hours = (place.get("regularOpeningHours") or {}).get("weekdayDescriptions")
    return {
        "id": place.get("id"),
        "name": (place.get("displayName") or {}).get("text"),
        "address": place.get("formattedAddress"),
        "lat": plat,
        "lng": plng,
        "rating": place.get("rating"),
        "rating_count": place.get("userRatingCount"),
        "price_level": PRICE_LEVEL_LABEL.get(place.get("priceLevel") or "", None),
        "hours": hours,
        # Structured hours for verification (see hours.py). Absent/None when Google has no data.
        "periods": (place.get("regularOpeningHours") or {}).get("periods"),
        "current_periods": (place.get("currentOpeningHours") or {}).get("periods"),
        "business_status": place.get("businessStatus"),
        "utc_offset_minutes": place.get("utcOffsetMinutes"),
        "types": place.get("types", [])[:4],
        "maps_url": place.get("googleMapsUri"),
        "website": place.get("websiteUri"),
        "distance_miles": round(haversine_miles(lat, lng, plat, plng), 1)
        if plat is not None and plng is not None
        else None,
        "verified": True,
    }


async def search_venues(query: str, lat: float, lng: float, radius_m: float, max_results: int = 6) -> list[dict]:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not key:
        return []
    body = {
        "textQuery": query,
        "maxResultCount": min(max_results, 20),
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": min(radius_m, 50000)}},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://places.googleapis.com/v1/places:searchText",
                json=body,
                headers={"Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": PLACES_FIELDS},
            )
        if resp.status_code >= 400:
            logger.warning("Places API error %s: %s", resp.status_code, resp.text[:200])
            return []
        return [_normalize(p, lat, lng) for p in resp.json().get("places", [])]
    except Exception as exc:  # network failures should never break spark generation
        logger.warning("Places API request failed: %s", exc)
        return []


async def geocode(query: str) -> Optional[dict[str, Any]]:
    """Resolve a city / ZIP to coordinates. Google Places text search first, Nominatim fallback."""
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://places.googleapis.com/v1/places:searchText",
                    json={"textQuery": query, "maxResultCount": 1},
                    headers={
                        "Content-Type": "application/json",
                        "X-Goog-Api-Key": key,
                        "X-Goog-FieldMask": "places.formattedAddress,places.location,places.displayName",
                    },
                )
            if resp.status_code < 400:
                places = resp.json().get("places", [])
                if places:
                    p = places[0]
                    return {
                        "label": (p.get("displayName") or {}).get("text") or p.get("formattedAddress"),
                        "lat": p["location"]["latitude"],
                        "lng": p["location"]["longitude"],
                    }
        except Exception as exc:
            logger.warning("Google geocode failed: %s", exc)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1},
                headers={"User-Agent": "DateSpark/1.0 (connection planning app)"},
            )
        data = resp.json()
        if data:
            name = data[0].get("display_name", query).split(",")
            return {"label": ", ".join(name[:2]).strip(), "lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])}
    except Exception as exc:
        logger.warning("Nominatim geocode failed: %s", exc)
    return None
