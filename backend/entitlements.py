"""Server-side RevenueCat entitlement verification (memory/revenuecat_server_verification_plan.md v3).

Trust model: nothing the client sends is evidence. Premium is decided from (a) signed RevenueCat webhooks and
(b) read-only REST lookups (`active_entitlements`, permission `customer_information:customers:read`). Identity is
exact: RevenueCat `app_user_id` == `users.id` (the app calls `Purchases.logIn(user.id)`); only ids that exist in
`users` with `deleted_at: null` ever receive state. Unknown users, first-time lookups that fail, and expired or
revoked subscriptions FAIL CLOSED. A 72 h grace applies ONLY to a user whose last verified state was active, whose
`expires_at` passed less than 72 h ago, and for whom a fresh lookup is transiently impossible (429/5xx/timeout).

Everything here is inert while `features.server_entitlements` is OFF (the caller never invokes `resolve()`).
Secrets live in the environment only and are never logged.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger("entitlements")

ENTITLEMENT_KEY = "pro"  # lookup key used by the app / webhooks
LOOKUP_TTL = timedelta(hours=24)
GRACE_WINDOW = timedelta(hours=72)
REPLAY_WINDOW_SECONDS = 300
LOOKUP_TIMEOUT_SECONDS = 5.0
API_BASE = "https://api.revenuecat.com/v2"

# Events after which the stored state is re-synced from REST (delivery order is irrelevant then).
ACCESS_CHANGING_EVENTS = {"CANCELLATION", "EXPIRATION", "BILLING_ISSUE", "TRANSFER", "PRODUCT_CHANGE", "SUBSCRIPTION_PAUSED"}
GRANTING_EVENTS = {"INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE", "SUBSCRIPTION_EXTENDED", "TEMPORARY_ENTITLEMENT_GRANT", "NON_RENEWING_PURCHASE"}
KNOWN_EVENTS = GRANTING_EVENTS | ACCESS_CHANGING_EVENTS | {"TEST", "TRANSFER"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ms(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- settings
@dataclass(frozen=True)
class Settings:
    secret_key: str
    webhook_secret: str
    webhook_auth: str
    project_id: str
    entitlement_id: str  # RevenueCat internal id (entl…) of the `pro` entitlement; empty = any active entitlement
    environment: str  # PRODUCTION | SANDBOX — events from the other environment are never applied

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            secret_key=os.environ.get("REVENUECAT_SECRET_KEY", "").strip(),
            webhook_secret=os.environ.get("REVENUECAT_WEBHOOK_SECRET", "").strip(),
            webhook_auth=os.environ.get("REVENUECAT_WEBHOOK_AUTH", "").strip(),
            project_id=os.environ.get("REVENUECAT_PROJECT_ID", "").strip(),
            entitlement_id=os.environ.get("REVENUECAT_ENTITLEMENT_ID", "").strip(),
            environment=os.environ.get("REVENUECAT_ENVIRONMENT", "PRODUCTION").strip().upper() or "PRODUCTION",
        )

    @property
    def lookups_configured(self) -> bool:
        return bool(self.secret_key and self.project_id)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.webhook_secret)

    def status(self) -> dict:
        """Safe for logs / admin: booleans only, never values."""
        return {"lookups_configured": self.lookups_configured, "webhook_configured": self.webhook_configured, "environment": self.environment, "entitlement_id_pinned": bool(self.entitlement_id)}


# ---------------------------------------------------------------- webhook signature
class SignatureError(Exception):
    pass


def verify_signature(raw_body: bytes, header: str | None, secret: str, now_ts: float | None = None) -> None:
    """`X-RevenueCat-Webhook-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "{t}.{raw body}">`.
    Raises SignatureError on any defect; the raw bytes must be used verbatim."""
    if not secret:
        raise SignatureError("webhook signing not configured")
    if not header:
        raise SignatureError("missing signature header")
    parts: dict[str, str] = {}
    for piece in header.split(","):
        if "=" in piece:
            k, v = piece.strip().split("=", 1)
            parts[k.strip()] = v.strip()
    ts, sig = parts.get("t"), parts.get("v1")
    if not ts or not sig or not ts.isdigit():
        raise SignatureError("malformed signature header")
    now_ts = now_ts if now_ts is not None else _now().timestamp()
    if abs(now_ts - int(ts)) > REPLAY_WINDOW_SECONDS:
        raise SignatureError("stale timestamp")
    expected = hmac.new(secret.encode(), ts.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig.lower()):
        raise SignatureError("signature mismatch")


def sign(raw_body: bytes, secret: str, ts: int) -> str:
    """Produce a valid header (tests / local tooling only)."""
    return f"t={ts},v1={hmac.new(secret.encode(), str(ts).encode() + b'.' + raw_body, hashlib.sha256).hexdigest()}"


# ---------------------------------------------------------------- REST lookup
class LookupFailure(Exception):
    """kind: auth (401/403 — nothing may be granted, abort batch jobs) · not_found (404 — never seen by RevenueCat)
    · rate_limited (429) · unavailable (5xx / network) · timeout · unconfigured."""

    TRANSIENT = {"rate_limited", "unavailable", "timeout"}

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail

    @property
    def transient(self) -> bool:
        return self.kind in self.TRANSIENT


@dataclass
class LookupResult:
    active: bool
    expires_at: datetime | None  # None with active=True means no expiry reported (lifetime)
    entitlement_ids: list[str]


class RevenueCatClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _get(self, url: str) -> tuple[int, Any]:  # patched in tests — the ONLY network touch point
        async with httpx.AsyncClient(timeout=LOOKUP_TIMEOUT_SECONDS) as http:
            r = await http.get(url, headers={"Authorization": f"Bearer {self.settings.secret_key}", "Accept": "application/json"})
            try:
                body = r.json()
            except ValueError:
                body = None
            return r.status_code, body

    async def active_entitlements(self, customer_id: str) -> LookupResult:
        s = self.settings
        if not s.lookups_configured:
            raise LookupFailure("unconfigured")
        url = f"{API_BASE}/projects/{s.project_id}/customers/{customer_id}/active_entitlements"
        try:
            status, body = await self._get(url)
        except httpx.TimeoutException:
            raise LookupFailure("timeout")
        except httpx.HTTPError as exc:
            raise LookupFailure("unavailable", type(exc).__name__)
        if status in (401, 403):
            raise LookupFailure("auth", str(status))
        if status == 404:
            raise LookupFailure("not_found")
        if status == 429:
            raise LookupFailure("rate_limited")
        if status >= 500 or status != 200 or not isinstance(body, dict):
            raise LookupFailure("unavailable", str(status))
        items = body.get("items") or []
        ids, expiries, active = [], [], False
        for it in items:
            if not isinstance(it, dict):
                continue
            eid = str(it.get("entitlement_id") or "")
            ids.append(eid)
            if s.entitlement_id and eid != s.entitlement_id:
                continue
            exp = _ms(it.get("expires_at"))
            if exp is None or exp > _now():
                active = True
                expiries.append(exp)
        expires_at = None if (active and any(e is None for e in expiries)) else (max(expiries) if expiries else None)
        return LookupResult(active=active, expires_at=expires_at, entitlement_ids=ids)


# ---------------------------------------------------------------- store + evaluation
class EntitlementStore:
    """`entitlements` (one doc per users.id) + `webhook_events` (audit, unique event id)."""

    def __init__(self, db: Any, settings: Settings, client: RevenueCatClient | None = None):
        self.db, self.settings = db, settings
        self.client = client or RevenueCatClient(settings)

    async def ensure_indexes(self) -> None:
        await self.db.entitlements.create_index("user_id", unique=True)
        await self.db.webhook_events.create_index("event_id", unique=True)
        await self.db.webhook_events.create_index([("received_at", -1)])

    async def _user_exists(self, user_id: str) -> bool:
        if not user_id:
            return False
        return await self.db.users.count_documents({"id": user_id, "deleted_at": None}, limit=1) > 0

    async def _persist(self, user_id: str, *, active: bool, expires_at: datetime | None, source: str, now: datetime, **extra: Any) -> dict:
        update: dict[str, Any] = {
            "entitlement": ENTITLEMENT_KEY,
            "active": active,
            "expires_at": expires_at,
            "source": source,
            "checked_at": now,
            "updated_at": now,
            **extra,
        }
        if active:
            update["verified_active_at"] = now
        return await self.db.entitlements.find_one_and_update(
            {"user_id": user_id},
            {"$set": update, "$setOnInsert": {"user_id": user_id, "created_at": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )

    async def lookup_and_store(self, user_id: str, now: datetime | None = None) -> dict:
        """REST truth → stored doc. Raises LookupFailure (auth/transient) — the caller decides fail-closed/grace.
        404 is stored as verified-not-premium."""
        now = now or _now()
        try:
            res = await self.client.active_entitlements(user_id)
        except LookupFailure as exc:
            if exc.kind != "not_found":
                raise
            return await self._persist(user_id, active=False, expires_at=None, source="lookup", now=now, lookup_status="not_found")
        return await self._persist(user_id, active=res.active, expires_at=res.expires_at, source="lookup", now=now, lookup_status="ok", rc_entitlement_ids=res.entitlement_ids)

    @staticmethod
    def is_current(doc: dict | None, now: datetime) -> bool:
        if not doc or not doc.get("active"):
            return False
        exp = _aware(doc.get("expires_at"))
        if exp is None or exp > now:
            return True
        grace = _aware(doc.get("grace_period_expires_at"))
        return bool(grace and grace > now)

    async def resolve(self, user_id: str, now: datetime | None = None) -> tuple[bool, str]:
        """(premium, reason). Never grants without stored or fresh evidence attributed to this exact user id."""
        now = now or _now()
        if not await self._user_exists(user_id):
            return False, "unknown_user"
        doc = await self.db.entitlements.find_one({"user_id": user_id}, {"_id": 0})
        checked = _aware(doc.get("checked_at")) if doc else None
        stale = doc is None or checked is None or now - checked > LOOKUP_TTL
        expired_active = bool(doc and doc.get("active") and not self.is_current(doc, now))
        failure: LookupFailure | None = None
        if stale or expired_active:
            try:
                doc = await self.lookup_and_store(user_id, now)
            except LookupFailure as exc:
                failure = exc
                if exc.kind == "auth":
                    logger.error("RevenueCat lookup rejected (%s) — check REVENUECAT_SECRET_KEY permissions", exc.kind)
        if doc is None:
            return False, f"no_evidence:{failure.kind if failure else 'unconfigured'}"
        if self.is_current(doc, now):
            return True, "verified"
        if failure is not None and failure.transient and doc.get("active"):
            exp = _aware(doc.get("expires_at"))
            if exp and now - exp < GRACE_WINDOW:
                logger.warning("entitlement grace grant for %s (lookup %s)", user_id[:8], failure.kind)
                await self.db.entitlements.update_one({"user_id": user_id}, {"$set": {"last_grace_at": now}})
                return True, f"grace:{failure.kind}"
        return False, "inactive"

    # ------------------------------------------------------------ webhooks
    async def record_event(self, event: dict, now: datetime | None = None) -> dict | None:
        """Store once; returns the stored doc or None when the id was already seen."""
        now = now or _now()
        doc = {
            "event_id": str(event.get("id") or ""),
            "type": event.get("type"),
            "app_user_id": event.get("app_user_id"),
            "original_app_user_id": event.get("original_app_user_id"),
            "environment": event.get("environment"),
            "event_timestamp_ms": event.get("event_timestamp_ms"),
            "received_at": now,
            "status": "received",
            "applied_to": [],
        }
        if not doc["event_id"]:
            doc["status"] = "rejected_no_id"
            return doc
        try:
            await self.db.webhook_events.insert_one(dict(doc))
        except DuplicateKeyError:
            return None
        return doc

    @staticmethod
    def state_from_event(event: dict, now: datetime) -> dict | None:
        """Event-derived state (used when a REST re-sync is impossible). None = event does not affect `pro`."""
        etype = event.get("type")
        ids = event.get("entitlement_ids") or []
        if ids and ENTITLEMENT_KEY not in ids and etype != "TRANSFER":
            return None
        exp = _ms(event.get("expiration_at_ms"))
        if etype in GRANTING_EVENTS:
            return {"active": exp is None or exp > now, "expires_at": exp}
        if etype == "CANCELLATION":
            refunded = event.get("cancel_reason") == "CUSTOMER_SUPPORT"
            return {"active": (not refunded) and bool(exp and exp > now), "expires_at": exp, "unsubscribe_at": now, **({"refunded_at": now} if refunded else {})}
        if etype == "EXPIRATION":
            return {"active": False, "expires_at": exp, "expiration_reason": event.get("expiration_reason")}
        if etype == "BILLING_ISSUE":
            grace = _ms(event.get("grace_period_expiration_at_ms"))
            return {"active": bool((exp and exp > now) or (grace and grace > now)), "expires_at": exp, "grace_period_expires_at": grace, "billing_issue_at": now}
        if etype == "SUBSCRIPTION_PAUSED":
            return {"active": bool(exp and exp > now), "expires_at": exp, "paused": True}
        return None

    async def apply_event(self, stored: dict, event: dict, now: datetime | None = None) -> dict:
        """Recompute state for every Date Spark user the event names. Unknown / deleted ids grant nothing."""
        now = now or _now()
        etype = event.get("type")
        event_at = _ms(event.get("event_timestamp_ms")) or now
        if etype == "TRANSFER":
            losers = [str(x) for x in (event.get("transferred_from") or [])]
            gainers = [str(x) for x in (event.get("transferred_to") or [])]
        else:
            losers, gainers = [], []
            for key in ("app_user_id", "original_app_user_id"):
                if event.get(key) and str(event[key]) not in gainers:
                    gainers.append(str(event[key]))
        results: dict[str, str] = {}
        for uid in losers + gainers:
            if not await self._user_exists(uid):
                results[uid] = "unknown_user"
                continue
            existing = await self.db.entitlements.find_one({"user_id": uid}, {"_id": 0})
            last = _aware(existing.get("last_event_at")) if existing else None
            if last and event_at < last and etype not in ACCESS_CHANGING_EVENTS:
                results[uid] = "stale_event_ignored"
                continue
            if etype == "TEST":
                results[uid] = "test_event"
                continue
            meta = {"last_event_at": event_at, "last_event_type": etype, "store": event.get("store"), "environment": event.get("environment")}
            note = ""
            if etype in ACCESS_CHANGING_EVENTS:
                try:
                    await self.lookup_and_store(uid, now)
                    await self.db.entitlements.update_one({"user_id": uid}, {"$set": meta})
                    results[uid] = "resynced"
                    continue
                except LookupFailure as exc:
                    note = f"lookup_failed:{exc.kind}:"
                    if uid in losers:  # losing side of a TRANSFER: revoke now, REST truth arrives on the next check
                        await self._persist(uid, active=False, expires_at=None, source="webhook", now=now, transferred=True, **meta)
                        results[uid] = note + "revoked"
                        continue
            state = self.state_from_event(event, now)
            if state is None:  # e.g. TRANSFER gainer without REST truth → nothing granted
                results[uid] = note + "not_applicable"
                continue
            await self._persist(uid, source="webhook", now=now, **meta, **state)
            results[uid] = note + "applied_from_event"
        await self.db.webhook_events.update_one({"event_id": stored["event_id"]}, {"$set": {"status": "processed", "applied_to": results, "processed_at": now}})
        return results

    async def handle_webhook(self, raw_body: bytes, signature: str | None, authorization: str | None, now: datetime | None = None) -> dict:
        """Full pipeline; raises SignatureError for 401. Always returns a dict for a 200."""
        now = now or _now()
        verify_signature(raw_body, signature, self.settings.webhook_secret, now.timestamp())
        if self.settings.webhook_auth and not hmac.compare_digest(authorization or "", self.settings.webhook_auth):
            raise SignatureError("authorization header mismatch")
        try:
            payload = json.loads(raw_body)
        except ValueError:
            raise SignatureError("invalid json")
        event = payload.get("event") if isinstance(payload, dict) else None
        if not isinstance(event, dict):
            raise SignatureError("missing event")
        stored = await self.record_event(event, now)
        if stored is None:
            return {"ok": True, "duplicate": True}
        if stored["status"] != "received":
            return {"ok": True, "ignored": stored["status"]}
        env = str(event.get("environment") or "").upper()
        if env and env != self.settings.environment:
            await self.db.webhook_events.update_one({"event_id": stored["event_id"]}, {"$set": {"status": "ignored_environment"}})
            return {"ok": True, "ignored": "environment"}
        try:
            applied = await self.apply_event(stored, event, now)
        except Exception as exc:  # persisted already; RevenueCat retries are harmless (duplicate id)
            logger.exception("webhook apply failed")
            await self.db.webhook_events.update_one({"event_id": stored["event_id"]}, {"$set": {"status": "error", "error": type(exc).__name__}})
            return {"ok": True, "error": type(exc).__name__}
        return {"ok": True, "applied": applied}

    # ------------------------------------------------------------ admin
    async def check(self, user_id: str, now: datetime | None = None) -> dict:
        now = now or _now()
        user = await self.db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "email": 1, "subscription_status": 1, "subscription_source": 1, "deleted_at": 1, "role": 1})
        doc = await self.db.entitlements.find_one({"user_id": user_id}, {"_id": 0})
        return {
            "user_id": user_id,
            "exists": bool(user and not user.get("deleted_at")),
            "role": (user or {}).get("role"),
            "self_reported_status": (user or {}).get("subscription_status"),
            "verified": doc,
            "verified_active_now": self.is_current(doc, now),
            "config": self.settings.status(),
        }

    async def backfill(self, *, dry_run: bool = True, limit: int = 1000, user_ids: list[str] | None = None, now: datetime | None = None) -> dict:
        """Reconcile non-deleted users (all, or the given ids) against RevenueCat by exact users.id. Aborts on auth
        errors (nothing granted); backs off on 429; never derives state from self-reported data. dry_run → report only."""
        now = now or _now()
        report: dict[str, Any] = {"dry_run": dry_run, "checked": 0, "verified_active": 0, "verified_inactive": 0, "never_seen": 0, "failed": 0, "aborted": None, "mismatches": []}
        if not self.settings.lookups_configured:
            report["aborted"] = "unconfigured"
            return report
        query: dict[str, Any] = {"deleted_at": None}
        if user_ids is not None:
            query["id"] = {"$in": list(user_ids)}
        cursor = self.db.users.find(query, {"_id": 0, "id": 1, "email": 1, "subscription_status": 1}).limit(limit)
        async for u in cursor:
            uid = u["id"]
            attempts = 0
            while True:
                try:
                    res = await self.client.active_entitlements(uid)
                    status = "active" if res.active else "inactive"
                    break
                except LookupFailure as exc:
                    if exc.kind == "auth":
                        report["aborted"] = "auth_error"
                        return report
                    if exc.kind == "not_found":
                        status, res = "never_seen", None
                        break
                    attempts += 1
                    if exc.kind == "rate_limited" and attempts <= 3:
                        await asyncio.sleep(min(2 ** attempts, 8))
                        continue
                    status, res = "failed", None
                    break
            report["checked"] += 1
            report[{"active": "verified_active", "inactive": "verified_inactive", "never_seen": "never_seen", "failed": "failed"}[status]] += 1
            if not dry_run and status != "failed":
                await self._persist(uid, active=bool(res and res.active), expires_at=res.expires_at if res else None, source="lookup", now=now, lookup_status="ok" if res else "not_found")
            self_premium = (u.get("subscription_status") or "free") != "free"
            if self_premium != (status == "active"):
                report["mismatches"].append({"user_id": uid, "self_reported": u.get("subscription_status"), "verified": status})
        return report
