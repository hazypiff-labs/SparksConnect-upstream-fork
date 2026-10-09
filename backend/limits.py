"""Server-side generation limits (Launch audit B-1/B-2).

Nothing the client sends is proof of anything: `X-Premium` is IGNORED for limits. Only a server-verified
entitlement (`premium_verified`, decided by the server from trusted data — today the admin role; later RevenueCat
server-side verification) unlocks the Premium lane; everyone else gets exactly the ordinary free quota. Every counter is an atomic Mongo `$inc` taken BEFORE any Claude / Google Places call, so concurrent
requests cannot slip past a cap, and the limiter is shared by all workers and survives restarts.

Layers (all admin-tunable via app_config.limits):
  1. per-IP            hourly + daily            — blunt abuse / scripted traffic, generous for shared NAT
  2. guest-ids per IP  daily                     — rotating X-Guest-ID stops yielding fresh free allowances
  3. per-identity      free: monthly (existing)  — user id for accounts, guest id for guests
                       verified premium: daily + monthly ceilings (never reachable by a client claim)

Fail-closed: if the counter store is unavailable the request is denied (429), never waved through.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from pymongo import ReturnDocument

logger = logging.getLogger("limits")

DEFAULT_LIMITS = {
    "ip_hourly_cap": 20,
    "ip_daily_cap": 80,
    "guest_ids_per_ip_daily": 20,
    "premium_daily_cap": 15,
    "premium_monthly_cap": 60,
}

LIMIT_FIELDS = tuple(DEFAULT_LIMITS)


def limits_from(cfg: dict) -> dict:
    out = dict(DEFAULT_LIMITS)
    for k, v in (cfg.get("limits") or {}).items():
        if k in out and isinstance(v, int) and v >= 0:
            out[k] = v
    return out


def trusted_proxy_hops() -> int:
    try:
        return max(0, int(os.environ.get("TRUSTED_PROXY_HOPS", "2")))
    except ValueError:
        return 2


def client_ip(request: Request) -> str:
    """Real client address behind the proxy chain. Observed chain on this platform: X-Forwarded-For =
    "<client>, <CDN>, <load balancer>" — two trusted hops append themselves, so the client is the entry
    TRUSTED_PROXY_HOPS+1 from the end. Anything the client prepends itself is further left and ignored; the
    last entries are shared infrastructure and must never be used (everyone would share one bucket).
    `CF-Connecting-IP` (set by the CDN) wins when present."""
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if xff:
        hops = trusted_proxy_hops()
        return xff[-(hops + 1)] if len(xff) > hops else xff[0]
    return request.client.host if request.client else "unknown"


def _windows(now: datetime) -> dict[str, tuple[str, datetime]]:
    hour = now.replace(minute=0, second=0, microsecond=0)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    next_month = (month + timedelta(days=32)).replace(day=1)
    return {
        "hour": (hour.strftime("%Y-%m-%dT%H"), hour + timedelta(hours=1)),
        "day": (day.strftime("%Y-%m-%d"), day + timedelta(days=1)),
        "month": (month.strftime("%Y-%m"), next_month),
    }


class LimitExceeded(Exception):
    def __init__(self, status: int, message: str, scope: str):
        super().__init__(message)
        self.status, self.message, self.scope = status, message, scope


class Limiter:
    def __init__(self, db: Any):
        self.db = db

    async def ensure_indexes(self) -> None:
        await self.db.rate_limits.create_index("key", unique=True)
        await self.db.rate_limits.create_index("expires_at", expireAfterSeconds=0)

    async def _reserve(self, key: str, cap: int, expires_at: datetime) -> int:
        """Atomically count one unit against `key`; returns the new count (caller compares with cap).
        Raises on store failure so the caller fails closed."""
        doc = await self.db.rate_limits.find_one_and_update(
            {"key": key},
            {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": expires_at}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc.get("count", 0))

    async def _release(self, key: str) -> None:
        try:
            await self.db.rate_limits.update_one({"key": key, "count": {"$gt": 0}}, {"$inc": {"count": -1}})
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("limit release failed: %s", exc)

    async def _is_new_guest(self, guest_id: str, expires_at: datetime) -> bool:
        res = await self.db.rate_limits.update_one({"key": f"guest-seen:{guest_id}"}, {"$setOnInsert": {"expires_at": expires_at, "count": 0}}, upsert=True)
        return res.upserted_id is not None

    async def reserve_generation(self, *, ip: str, owner_type: str, owner_id: str, premium_verified: bool, cfg: dict, now: datetime | None = None) -> dict:
        """Take every applicable unit for one generation or raise LimitExceeded. Returns a receipt for `release()`.
        Order: IP → guest rotation → identity, so expensive identity windows aren't consumed by blocked traffic."""
        lim = limits_from(cfg)
        now = now or datetime.now(timezone.utc)
        w = _windows(now)
        taken: list[str] = []
        try:
            # 1. per-IP
            for window, cap, msg in (("hour", lim["ip_hourly_cap"], "hour"), ("day", lim["ip_daily_cap"], "day")):
                key = f"ip:{ip}:{window}:{w[window][0]}"
                taken.append(key)
                if await self._reserve(key, cap, w[window][1]) > cap:
                    raise LimitExceeded(429, f"Too many Sparks from your network this {msg}. Please try again later.", "ip")
            # 2. guest-id rotation per IP
            if owner_type == "guest":
                if await self._is_new_guest(owner_id, w["month"][1]):
                    key = f"ipguests:{ip}:{w['day'][0]}"
                    taken.append(key)
                    if await self._reserve(key, lim["guest_ids_per_ip_daily"], w["day"][1]) > lim["guest_ids_per_ip_daily"]:
                        raise LimitExceeded(429, "Too many new guest sessions from your network today. Sign in to keep creating Sparks.", "guest_rotation")
            # 3. identity ceilings
            ident = f"{owner_type}:{owner_id}"
            if premium_verified:
                for window, cap, msg in (("day", lim["premium_daily_cap"], "today"), ("month", lim["premium_monthly_cap"], "this month")):
                    key = f"id:{ident}:premium:{window}:{w[window][0]}"
                    taken.append(key)
                    if await self._reserve(key, cap, w[window][1]) > cap:
                        raise LimitExceeded(429, f"You've reached the Spark limit for {msg}. It resets automatically.", "premium_ceiling")
            else:
                key = f"id:{ident}:free:month:{w['month'][0]}"
                taken.append(key)
                if await self._reserve(key, cfg["free_spark_limit"], w["month"][1]) > cfg["free_spark_limit"]:
                    raise LimitExceeded(402, "You've used this month's free Sparks. Upgrade to Premium for more Sparks.", "free_quota")
        except LimitExceeded:
            # the blocked unit itself stays counted (attempts count); earlier units are legitimately consumed
            raise
        except Exception as exc:
            logger.error("rate limiter unavailable — failing closed: %s", type(exc).__name__)
            raise LimitExceeded(429, "We can't create Sparks right now. Please try again in a moment.", "limiter_unavailable")
        return {"keys": taken}

    async def release(self, receipt: dict) -> None:
        """Give identity units back when generation fails after reservation (IP units stay — they bound load)."""
        for key in receipt.get("keys", []):
            if key.startswith("id:"):
                await self._release(key)

    async def free_used(self, owner_type: str, owner_id: str, now: datetime | None = None) -> int:
        w = _windows(now or datetime.now(timezone.utc))
        doc = await self.db.rate_limits.find_one({"key": f"id:{owner_type}:{owner_id}:free:month:{w['month'][0]}"}, {"_id": 0, "count": 1})
        return int((doc or {}).get("count", 0))
