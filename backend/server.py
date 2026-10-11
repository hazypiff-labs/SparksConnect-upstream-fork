import asyncio
import html
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

import httpx
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import places  # noqa: E402
from places import geocode  # noqa: E402
from entitlements import EntitlementStore, Settings as RCSettings, SignatureError, WebhookRetry  # noqa: E402
from identity import CodeStore, Mailer, ProviderError, ProviderIdentity, apple_exchange_code, apple_revoke, verify_apple_token, verify_google_token  # noqa: E402
from limits import DEFAULT_LIMITS, LimitExceeded, Limiter, client_ip  # noqa: E402
from recommend import generate_sparks  # noqa: E402
from routing import RouteCache  # noqa: E402

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out)


# LOG_FORMAT=json for log aggregation in production; the readable format stays the default for development.
_handler = logging.StreamHandler()
_handler.setFormatter(_JsonFormatter() if os.environ.get("LOG_FORMAT") == "json" else logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler])
logger = logging.getLogger("datespark")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
route_cache = RouteCache(db)
limiter = Limiter(db)
rc_settings = RCSettings.from_env()
entitlements = EntitlementStore(db, rc_settings)
codes = CodeStore(db)
mailer = Mailer(db)

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
TOKEN_DAYS = 30
password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummy-password-not-used")
NO_ID = {"_id": 0}
ANALYTICS_RETENTION_DAYS = 400  # raw events are deleted after ~13 months (audit N13)

DEFAULT_CONFIG = {
    "free_spark_limit": 3,
    "premium_price": 24.99,
    "trial_days": 14,
    "promo_message": "Make every moment count. Try Premium free for 2 weeks ✨",
    "featured_experiences": [
        {"title": "Golden Hour Picnic", "tagline": "Market snacks → Sunset spot → Stargazing", "vibe": "Romantic"},
        {"title": "Game Night Out", "tagline": "Arcade → Tacos → Late-night dessert", "vibe": "Fun & Playful"},
    ],
    "ai_settings": {"model": "claude-sonnet-4-6", "guidance": "Prioritize conversation-friendly, memorable moments."},
    # Feature flags — toggled from the admin dashboard, no redeploy needed
    # real_routing stays OFF until the Google Routes API is enabled on the project and activation is approved.
    # server_entitlements stays OFF until the RevenueCat webhook + read-only key are registered and the back-fill reviewed
    # (memory/revenuecat_rollout_runbook.md). OFF == Phase A behaviour exactly.
    "features": {"generation_enabled": True, "experience_profiles": True, "experience_builder": True, "experience_output": True, "venue_hours": True, "real_routing": False, "server_entitlements": False},
    # Server-side generation limits (Launch audit B-1/B-2). X-Premium only selects the bounded premium ceiling.
    "limits": dict(DEFAULT_LIMITS),
}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    await startup()
    yield
    client.close()


app = FastAPI(title="Date Spark API", lifespan=lifespan)
api = APIRouter(prefix="/api")


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- models
# Every client-supplied string/list is bounded (audit H4/H5): these values reach the LLM prompt, analytics and storage.
Short = Annotated[str, Field(max_length=40)]
Title = Annotated[str, Field(max_length=120)]


class Location(BaseModel):
    """The only location shape the API stores. Unknown keys are dropped so nothing else rides along (audit M1)."""

    model_config = ConfigDict(extra="ignore")
    label: Optional[str] = Field(default=None, max_length=120)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


def clean_location(v: Any) -> dict[str, Any] | None:
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("location must be an object")
    return Location(**v).model_dump(exclude_none=True)


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class AppleAuthIn(BaseModel):
    identity_token: str = Field(max_length=4096)
    name: Optional[str] = Field(default=None, max_length=80)
    # One-time code from the native sheet; exchanged for a refresh token so the grant can be revoked on account deletion.
    authorization_code: Optional[str] = Field(default=None, max_length=512)
    # NOTE: any client-sent `email` is ignored — identity comes from the verified token only (audit C1).


class GoogleAuthIn(BaseModel):
    id_token: str = Field(max_length=4096)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=128)


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    location: Optional[dict[str, Any]] = None

    @field_validator("location")
    @classmethod
    def _location(cls, v):
        return clean_location(v)


class PreferencesIn(BaseModel):
    relationship_preferences: list[Short] = Field(default_factory=list, max_length=20)
    favorite_vibes: list[Short] = Field(default_factory=list, max_length=20)
    budget_preferences: list[Short] = Field(default_factory=list, max_length=20)
    distance_preferences: list[Short] = Field(default_factory=list, max_length=20)


class SubscriptionSync(BaseModel):
    status: str = Field(max_length=16)  # free | trial | premium
    provider: str = Field(default="revenuecat", max_length=32)
    renewal_date: Optional[str] = Field(default=None, max_length=40)


class GenerateIn(BaseModel):
    relationship_type: str = Field(max_length=32)
    vibes: list[Short] = Field(default_factory=list, max_length=8)  # required unless surprise_me (validated below)
    budget: str = Field(max_length=32)
    distance: str = Field(max_length=16)
    location: dict[str, Any] = Field(default_factory=dict)
    exclude_titles: list[Title] = Field(default_factory=list, max_length=30)
    date_label: Optional[str] = Field(default=None, max_length=64)
    time_label: Optional[str] = Field(default=None, max_length=64)
    occasion: Optional[str] = Field(default=None, max_length=120)
    surprise: bool = False
    # --- Experience Engine foundation (all optional; defaults reproduce the original behaviour) ---
    experience_type: Optional[str] = Field(default=None, max_length=32)  # couple | friends | family | celebration | travel | solo | surprise_me
    party_size: Optional[int] = Field(default=None, ge=1, le=50)
    budget_amount: Optional[float] = Field(default=None, ge=0, le=100000)  # free-form total budget in USD
    duration_hours: Optional[float] = Field(default=None, gt=0, le=24)
    interests: list[Short] = Field(default_factory=list, max_length=20)
    transport: Optional[str] = Field(default=None, max_length=16)  # walk | transit | drive
    scheduled_at: Optional[str] = Field(default=None, max_length=40)  # ISO datetime when the experience should start
    surprise_me: bool = False  # engine picks the vibes itself (additive, distinct from `surprise`)

    @field_validator("location")
    @classmethod
    def _location(cls, v):
        return clean_location(v) or {}

    @model_validator(mode="after")
    def _vibes_required_unless_surprise_me(self):
        if not self.vibes and not self.surprise_me:
            raise ValueError("vibes: at least one vibe is required")
        return self

    def resolved_experience_type(self) -> str:
        """Derive the experience profile. Legacy requests (no experience_type) map onto the original dating semantics."""
        if self.experience_type:
            return self.experience_type.lower()
        # "Surprise me" is a planning preference, not a profile — the profile still comes from the company/occasion.
        if self.occasion:
            return "celebration"
        rel = self.relationship_type.lower()
        return {"friends": "friends", "group": "friends", "family": "family", "solo": "solo"}.get(rel, "couple")

    def experience_context(self) -> dict[str, Any]:
        """Only the fields the caller actually supplied, so the legacy prompt is unchanged when nothing new is sent."""
        ctx: dict[str, Any] = {}
        if self.experience_type:
            ctx["experience_type"] = self.experience_type.lower()
        if self.party_size is not None:
            ctx["party_size"] = self.party_size
        if self.budget_amount is not None:
            ctx["budget_amount"] = self.budget_amount
        if self.duration_hours is not None:
            ctx["duration_hours"] = self.duration_hours
        if self.interests:
            ctx["interests"] = self.interests
        if self.transport:
            ctx["transport"] = self.transport.lower()
        if self.scheduled_at:
            ctx["scheduled_at"] = self.scheduled_at
        if self.surprise_me:
            ctx["surprise_me"] = True
        return ctx


class ScheduleIn(BaseModel):
    date_label: Optional[str] = Field(default=None, max_length=64)
    time_label: Optional[str] = Field(default=None, max_length=64)
    scheduled_at: Optional[str] = Field(default=None, max_length=40)
    share_url: Optional[str] = Field(default=None, max_length=300)


# Events the app may report. Everything else (e.g. sparks_generated, entitlement_verified) is written only by the
# server, so a client can neither inflate usage counters nor poison admin metrics (audit H5).
CLIENT_EVENTS = {
    "app_opened", "signup_started", "premium_viewed", "location_selected", "spark_started", "vibe_selected",
    "surprise_me_toggled", "subscription_started", "spark_viewed", "spark_accepted", "relationship_selected",
    "experience_type_selected", "budget_selected", "restore_started", "share_opened",
}
MAX_EVENT_PROPS_BYTES = 2048


class EventIn(BaseModel):
    event: str = Field(max_length=64)
    props: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event")
    @classmethod
    def _allowed(cls, v):
        if v not in CLIENT_EVENTS:
            raise ValueError("unknown event")
        return v

    @field_validator("props")
    @classmethod
    def _small(cls, v):
        if len(json.dumps(v, default=str)) > MAX_EVENT_PROPS_BYTES:
            raise ValueError("props too large")
        return v


class ConfigUpdate(BaseModel):
    free_spark_limit: Optional[int] = Field(default=None, ge=0, le=1000)
    premium_price: Optional[float] = Field(default=None, ge=0)
    trial_days: Optional[int] = Field(default=None, ge=0)
    promo_message: Optional[str] = Field(default=None, max_length=300)
    featured_experiences: Optional[list[dict[str, Any]]] = None
    ai_settings: Optional[dict[str, Any]] = None
    features: Optional[dict[str, bool]] = None
    limits: Optional[dict[str, int]] = None


# ---------------------------------------------------------------- identity
def public_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "name": u.get("name", ""),
        "email": u["email"],
        "email_verified": bool(u.get("email_verified")),
        "role": u.get("role", "user"),
        "location": u.get("location"),
        "subscription_status": u.get("subscription_status", "free"),
        "subscription_start": iso(u.get("subscription_start")),
        "subscription_end": iso(u.get("subscription_end")),
        "created_at": iso(u.get("created_at")),
    }


def make_token(user: dict) -> str:
    return jwt.encode(
        # `tv` = token_version: bumped on password reset, account deletion and unverified-account takeover so every
        # previously issued token stops working.
        {"sub": user["id"], "role": user.get("role", "user"), "tv": int(user.get("token_version", 0)), "iat": now(), "exp": now() + timedelta(days=TOKEN_DAYS)},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


async def user_from_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid or expired token")
    user = await db.users.find_one({"id": claims.get("sub"), "deleted_at": None}, NO_ID)
    if not user or int(claims.get("tv", 0)) != int(user.get("token_version", 0)):
        raise HTTPException(401, "Invalid or expired token")
    return user


async def optional_user(authorization: Annotated[str | None, Header()] = None) -> dict | None:
    if authorization and authorization.startswith("Bearer "):
        return await user_from_token(authorization[7:])
    return None


async def require_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required")
    return await user_from_token(authorization[7:])


async def require_admin(user: Annotated[dict, Depends(require_user)]) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return user


class Identity(BaseModel):
    owner_type: str  # user | guest
    owner_id: str
    user: dict | None = None


async def identity(
    user: Annotated[dict | None, Depends(optional_user)],
    x_guest_id: Annotated[str | None, Header()] = None,
) -> Identity:
    if user:
        return Identity(owner_type="user", owner_id=user["id"], user=user)
    if x_guest_id and 8 <= len(x_guest_id) <= 64:
        return Identity(owner_type="guest", owner_id=x_guest_id)
    raise HTTPException(400, "Missing identity (X-Guest-ID header or bearer token)")


async def get_config() -> dict:
    cfg = await db.app_config.find_one({"key": "main"}, NO_ID)
    merged = {**DEFAULT_CONFIG, **(cfg or {})}
    merged["features"] = {**DEFAULT_CONFIG["features"], **((cfg or {}).get("features") or {})}
    merged["limits"] = {**DEFAULT_CONFIG["limits"], **{k: v for k, v in ((cfg or {}).get("limits") or {}).items() if k in DEFAULT_LIMITS}}
    merged.pop("key", None)
    return merged


async def track(event: str, ident: Identity | None, props: dict | None = None):
    await db.analytics_events.insert_one(
        {
            "id": str(uuid.uuid4()),
            "event": event,
            "owner_type": ident.owner_type if ident else None,
            "owner_id": ident.owner_id if ident else None,
            "props": props or {},
            "created_at": now(),
        }
    )


# ---------------------------------------------------------------- startup
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.users.create_index("apple_sub", unique=True, sparse=True)
    await db.users.create_index("google_sub", unique=True, sparse=True)
    # Accounts deleted before the fix kept their provider ids, which blocked the same Apple/Google account from ever
    # signing up again (unique index). Release them; deleted rows never match a login anyway.
    await db.users.update_many({"deleted_at": {"$ne": None}, "$or": [{"apple_sub": {"$exists": True}}, {"google_sub": {"$exists": True}}]}, {"$unset": {"apple_sub": "", "google_sub": "", "apple_refresh_token": ""}})
    await codes.ensure_indexes()
    await db.geocode_cache.create_index("q", unique=True)
    await db.geocode_cache.create_index("expires_at", expireAfterSeconds=0)

    async def places_budget() -> bool:
        cfg = await get_config()
        return await limiter.hit("global:places", cfg["limits"]["places_calls_daily"], timedelta(days=1))

    places.set_budget_guard(places_budget)
    await db.sparks.create_index([("owner_type", 1), ("owner_id", 1), ("created_at", -1)])
    await db.sparks.create_index("id", unique=True)
    await route_cache.ensure_indexes()
    await limiter.ensure_indexes()
    await entitlements.ensure_indexes()
    logger.info("RevenueCat server verification: %s", rc_settings.status())
    await db.saved_sparks.create_index([("owner_type", 1), ("owner_id", 1), ("spark_id", 1)])
    await db.analytics_events.create_index([("event", 1), ("created_at", -1)])
    await db.analytics_events.create_index("created_at", name="analytics_retention", expireAfterSeconds=ANALYTICS_RETENTION_DAYS * 86400)
    admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if admin_email and admin_pw:
        # Create the admin only when the address is unused. An existing account is NEVER promoted (it could belong to
        # anyone who registered that address first) and a deleted one is never resurrected (audit N11).
        existing = await db.users.find_one({"email": admin_email}, {"_id": 0, "role": 1})
        if not existing:
            try:
                await db.users.insert_one(
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Admin",
                        "email": admin_email,
                        "email_verified": True,
                        "password_hash": password_hash.hash(admin_pw),
                        "role": "admin",
                        "subscription_status": "free",
                        "token_version": 0,
                        "created_at": now(),
                        "deleted_at": None,
                    }
                )
            except DuplicateKeyError:  # another worker seeded it first
                pass
        elif existing.get("role") != "admin":
            logger.warning("ADMIN_EMAIL belongs to an existing non-admin account; not promoting it. Grant admin manually.")


# ---------------------------------------------------------------- public config
@api.get("/config/public")
async def public_config():
    cfg = await get_config()
    return {k: cfg[k] for k in ("free_spark_limit", "premium_price", "trial_days", "promo_message", "featured_experiences", "features")}


GEOCODE_TTL = timedelta(days=30)


@api.get("/places/geocode")
async def geocode_route(request: Request, ident: Annotated[Identity, Depends(identity)], q: str = Query(min_length=2, max_length=120)):
    """Billed upstream (Google Places), so it needs an identity, is throttled per IP and cached (audit H2)."""
    query = " ".join(q.split()).lower()
    cfg = await get_config()
    if not await limiter.hit(f"geocode:{client_ip(request)}", cfg["limits"]["geocode_ip_hourly"], timedelta(hours=1)):
        raise HTTPException(429, "Too many location lookups. Please try again in a bit.")
    cached = await db.geocode_cache.find_one({"q": query}, {"_id": 0, "result": 1})
    if cached:
        result = cached["result"]
    else:
        result = await geocode(query)
        await db.geocode_cache.update_one({"q": query}, {"$set": {"result": result, "expires_at": now() + GEOCODE_TTL}}, upsert=True)
    if not result:
        raise HTTPException(404, "We couldn't find that place. Try a city name or ZIP code.")
    return result


# ---------------------------------------------------------------- auth
async def migrate_guest(guest_id: str | None, user_id: str):
    if not guest_id:
        return
    update = {"$set": {"owner_type": "user", "owner_id": user_id}}
    q = {"owner_type": "guest", "owner_id": guest_id}
    await db.sparks.update_many(q, update)
    await db.saved_sparks.update_many(q, update)
    await db.analytics_events.update_many(q, update)


# Auth throttles: attempts per hour, admin-tunable via app_config.limits (fixed windows, fail closed).
AUTH_LIMIT_KEYS = {"login_ip": "auth_login_ip_hourly", "login_email": "auth_login_email_hourly", "signup_ip": "auth_signup_ip_hourly", "social_ip": "auth_social_ip_hourly"}
CODE_SEND_HOURLY = 5


async def throttle(name: str, subject: str) -> None:
    cap = CODE_SEND_HOURLY if name == "code_send" else (await get_config())["limits"][AUTH_LIMIT_KEYS[name]]
    if not await limiter.hit(f"auth:{name}:{subject}", cap, timedelta(hours=1)):
        raise HTTPException(429, "Too many attempts. Please wait a bit and try again.")


async def send_verification(user: dict) -> None:
    if user.get("email_verified") or user["email"].endswith(".invalid"):
        return
    code = await codes.issue("verify_email", user["id"])
    await mailer.send(user["email"], "Your Date Spark verification code", f"Your Date Spark code is {code}. It expires in 15 minutes.", "verify_email")


def auth_response(user: dict) -> dict:
    return {"access_token": make_token(user), "user": public_user(user)}


@api.post("/auth/signup")
async def signup(data: SignupIn, request: Request, x_guest_id: Annotated[str | None, Header()] = None):
    await throttle("signup_ip", client_ip(request))
    email = data.email.lower()
    user = {
        "id": str(uuid.uuid4()),
        "name": data.name.strip(),
        "email": email,
        "email_verified": False,
        "password_hash": password_hash.hash(data.password),
        "role": "user",
        "location": None,
        "subscription_status": "free",
        "token_version": 0,
        "created_at": now(),
        "deleted_at": None,
    }
    try:
        await db.users.insert_one(dict(user))
    except DuplicateKeyError:  # also covers concurrent signups for the same address (audit M3)
        raise HTTPException(409, "That email is already registered. Try logging in.")
    await migrate_guest(x_guest_id, user["id"])
    await track("signup_completed", Identity(owner_type="user", owner_id=user["id"]), {"provider": "email"})
    await send_verification(user)
    return auth_response(user)


@api.post("/auth/login")
async def login(data: LoginIn, request: Request, x_guest_id: Annotated[str | None, Header()] = None):
    email = data.email.lower()
    await throttle("login_ip", client_ip(request))
    await throttle("login_email", email)
    user = await db.users.find_one({"email": email, "deleted_at": None}, NO_ID)
    valid = password_hash.verify(data.password, user["password_hash"] if user and user.get("password_hash") else DUMMY_HASH)
    if not user or not user.get("password_hash") or not valid:
        raise HTTPException(401, "Incorrect email or password")
    await migrate_guest(x_guest_id, user["id"])
    return auth_response(user)


@api.get("/auth/me")
async def me(user: Annotated[dict, Depends(require_user)]):
    return public_user(user)


@api.post("/auth/verify-email/request")
async def verify_email_request(user: Annotated[dict, Depends(require_user)]):
    if user.get("email_verified"):
        return {"ok": True, "already_verified": True}
    await throttle("code_send", f"verify:{user['id']}")
    await send_verification(user)
    return {"ok": True}


@api.post("/auth/verify-email/confirm")
async def verify_email_confirm(data: CodeIn, user: Annotated[dict, Depends(require_user)]):
    if user.get("email_verified"):
        return public_user(user)
    if not await codes.consume("verify_email", user["id"], data.code):
        raise HTTPException(400, "That code is wrong or has expired. Request a new one.")
    await db.users.update_one({"id": user["id"]}, {"$set": {"email_verified": True, "email_verified_at": now()}})
    user["email_verified"] = True
    return public_user(user)


@api.post("/auth/password/forgot")
async def password_forgot(data: ForgotIn, request: Request):
    """Always 200 with the same body, so the endpoint cannot be used to discover which emails have accounts."""
    email = data.email.lower()
    await throttle("code_send", f"reset-ip:{client_ip(request)}")
    if await limiter.hit(f"auth:reset_email:{email}", 3, timedelta(hours=1)):
        user = await db.users.find_one({"email": email, "deleted_at": None}, {"_id": 0, "id": 1})
        if user:
            code = await codes.issue("reset_password", email)
            await mailer.send(email, "Reset your Date Spark password", f"Your Date Spark password reset code is {code}. It expires in 15 minutes. If you didn't ask for this, ignore this email.", "reset_password")
    return {"ok": True}


@api.post("/auth/password/reset")
async def password_reset(data: ResetIn, request: Request):
    email = data.email.lower()
    await throttle("login_ip", client_ip(request))
    if not await codes.consume("reset_password", email, data.code):
        raise HTTPException(400, "That code is wrong or has expired. Request a new one.")
    user = await db.users.find_one_and_update(
        {"email": email, "deleted_at": None},
        # Resetting proves control of the inbox: the email is verified and every older session is revoked.
        {"$set": {"password_hash": password_hash.hash(data.new_password), "email_verified": True}, "$inc": {"token_version": 1}},
        projection=NO_ID,
        return_document=True,
    )
    if not user:
        raise HTTPException(400, "That code is wrong or has expired. Request a new one.")
    return auth_response(user)


def _placeholder_email(pid: ProviderIdentity) -> str:
    return f"{pid.provider}-{pid.sub}@users.invalid"


async def social_login(pid: ProviderIdentity, x_guest_id: str | None, name: str | None = None, extra: dict | None = None) -> dict:
    """Find-or-create by the provider's stable subject id. Email-based linking happens ONLY when the provider vouches
    for the email (`email_verified`) — client-supplied emails are never used (audit C1). If the matching account's
    own email was never verified, whoever created it never proved they own the inbox (squatting, audit N1): the
    verified provider identity claims it, its password is removed and all of its sessions are revoked."""
    field = f"{pid.provider}_sub"
    extra = extra or {}
    user = await db.users.find_one({field: pid.sub, "deleted_at": None}, NO_ID)
    if not user and pid.email and pid.email_verified:
        existing = await db.users.find_one({"email": pid.email, "deleted_at": None}, NO_ID)
        if existing and not existing.get(field):
            update: dict[str, Any] = {"$set": {field: pid.sub, **extra}}
            if not existing.get("email_verified"):
                update["$set"].update({"email_verified": True, "password_hash": None})
                update["$inc"] = {"token_version": 1}
                await track("unverified_account_claimed", Identity(owner_type="user", owner_id=existing["id"]), {"provider": pid.provider})
            user = await db.users.find_one_and_update({"id": existing["id"]}, update, projection=NO_ID, return_document=True)
    if not user:
        email_taken = bool(pid.email) and await db.users.count_documents({"email": pid.email}, limit=1) > 0
        use_email = pid.email if (pid.email and pid.email_verified and not email_taken) else _placeholder_email(pid)
        user = {
            "id": str(uuid.uuid4()),
            "name": (name or pid.name or "").strip()[:80] or "Spark friend",
            "email": use_email,
            "email_verified": use_email == pid.email,
            field: pid.sub,
            "password_hash": None,
            "role": "user",
            "location": None,
            "subscription_status": "free",
            "token_version": 0,
            "created_at": now(),
            "deleted_at": None,
            **extra,
        }
        try:
            await db.users.insert_one(dict(user))
        except DuplicateKeyError:  # concurrent first sign-in with the same provider account
            user = await db.users.find_one({field: pid.sub, "deleted_at": None}, NO_ID)
            if not user:
                raise HTTPException(409, "Please try signing in again.")
        else:
            await track("signup_completed", Identity(owner_type="user", owner_id=user["id"]), {"provider": pid.provider})
    else:
        sets = dict(extra)
        if name and user.get("name") in (None, "", "Spark friend"):
            sets["name"] = name.strip()[:80]
        if sets:
            await db.users.update_one({"id": user["id"]}, {"$set": sets})
            user.update(sets)
    await migrate_guest(x_guest_id, user["id"])
    return auth_response(user)


@api.post("/auth/apple")
async def apple_login(data: AppleAuthIn, request: Request, x_guest_id: Annotated[str | None, Header()] = None):
    await throttle("social_ip", client_ip(request))
    try:
        pid = verify_apple_token(data.identity_token)
    except ProviderError as exc:
        logger.warning("Apple token rejected: %s", exc)
        raise HTTPException(401, "Apple sign-in could not be verified")
    extra = {}
    if data.authorization_code:
        refresh = await apple_exchange_code(data.authorization_code)
        if refresh:
            extra["apple_refresh_token"] = refresh
    return await social_login(pid, x_guest_id, name=data.name, extra=extra)


@api.post("/auth/google")
async def google_login(data: GoogleAuthIn, request: Request, x_guest_id: Annotated[str | None, Header()] = None):
    """Native Google Sign-In: the app sends the Google ID token; it is verified here against Google's keys and one of
    GOOGLE_CLIENT_IDS (replaces the Emergent demo-auth session exchange, audit H3)."""
    await throttle("social_ip", client_ip(request))
    try:
        pid = verify_google_token(data.id_token)
    except ProviderError as exc:
        logger.warning("Google token rejected: %s", exc)
        raise HTTPException(401, "Google sign-in could not be verified")
    extra = {"google_linked": True, **({"picture": pid.picture} if pid.picture else {})}
    return await social_login(pid, x_guest_id, extra=extra)


@api.put("/users/me")
async def update_me(data: ProfileUpdate, user: Annotated[dict, Depends(require_user)]):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
    fresh = await db.users.find_one({"id": user["id"]}, NO_ID)
    return public_user(fresh)


@api.delete("/auth/account")
async def delete_account(user: Annotated[dict, Depends(require_user)]):
    """Deletes the account's personal data and content. A tombstone row (id + deleted_at) remains so ids are never
    reused and RevenueCat events for the id are ignored. Provider links are removed (the same Apple/Google account
    can sign up again), every token is revoked, and the Sign in with Apple grant is revoked when we hold one."""
    if user.get("apple_refresh_token"):
        try:
            await apple_revoke(user["apple_refresh_token"])
        except Exception as exc:  # never block deletion on Apple's availability
            logger.error("Apple revoke failed: %s", type(exc).__name__)
    uid = user["id"]
    mine = {"owner_type": "user", "owner_id": uid}
    await db.users.update_one(
        {"id": uid},
        {
            "$set": {"deleted_at": now(), "email": f"deleted-{uid}@deleted.invalid", "name": "Deleted user", "location": None, "password_hash": None, "email_verified": False, "picture": None},
            "$unset": {"apple_sub": "", "google_sub": "", "apple_refresh_token": ""},
            "$inc": {"token_version": 1},
        },
    )
    await db.sparks.delete_many(mine)
    await db.saved_sparks.delete_many(mine)
    await db.user_preferences.delete_many(mine)
    await db.subscriptions.delete_many({"user_id": uid})
    await db.auth_codes.delete_many({"subject": {"$in": [uid, user.get("email")]}})
    await db.analytics_events.update_many(mine, {"$set": {"owner_id": "deleted", "props": {}}})
    return {"ok": True}


@api.get("/users/me/preferences")
async def get_preferences(ident: Annotated[Identity, Depends(identity)]):
    prefs = await db.user_preferences.find_one({"owner_type": ident.owner_type, "owner_id": ident.owner_id}, NO_ID)
    return prefs or PreferencesIn().model_dump()


@api.put("/users/me/preferences")
async def put_preferences(data: PreferencesIn, ident: Annotated[Identity, Depends(identity)]):
    await db.user_preferences.update_one(
        {"owner_type": ident.owner_type, "owner_id": ident.owner_id},
        {"$set": {**data.model_dump(), "updated_at": now()}},
        upsert=True,
    )
    return data


@api.put("/users/me/subscription")
async def sync_subscription(data: SubscriptionSync, user: Annotated[dict, Depends(require_user)]):
    """Advisory, SELF-REPORTED mirror of the on-device RevenueCat entitlement. It is never used for access
    decisions or limits (see limits.py) and is labelled as self-reported wherever it is shown."""
    status = data.status if data.status in ("free", "trial", "premium") else "free"
    updates: dict[str, Any] = {"subscription_status": status, "subscription_source": "self_reported"}
    if status != "free" and not user.get("subscription_start"):
        updates["subscription_start"] = now()
    if status == "free":
        updates["subscription_end"] = now()
    await db.users.update_one({"id": user["id"]}, {"$set": updates})
    await db.subscriptions.update_one(
        {"user_id": user["id"]},
        {
            "$set": {
                "plan": "premium_monthly" if status != "free" else "free",
                "status": status,
                "provider": data.provider,
                "source": "self_reported",
                "renewal_date": data.renewal_date,
                "updated_at": now(),
            },
            "$setOnInsert": {"id": str(uuid.uuid4()), "start_date": now()},
        },
        upsert=True,
    )
    return {"ok": True, "subscription_status": status}


# ---------------------------------------------------------------- sparks
def month_start() -> datetime:
    n = now()
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def verified_entitlement(ident: Identity, cfg: dict | None = None) -> bool:
    """Server-side truth for Premium limits. Guests can never be verified. The admin role (JWT + DB) is always
    trusted. With `features.server_entitlements` ON, paying users are verified from RevenueCat data the server
    trusts (signed webhooks + read-only REST lookups, see entitlements.py); OFF == Phase A. Client claims (X-Premium,
    subscription mirror) are never consulted."""
    if ident.owner_type != "user":
        return False
    u = await db.users.find_one({"id": ident.owner_id, "deleted_at": None}, {"_id": 0, "role": 1})
    if not u:
        return False
    if u.get("role") == "admin":
        return True
    cfg = cfg or await get_config()
    if not cfg.get("features", {}).get("server_entitlements", False):
        return False
    try:
        premium, reason = await entitlements.resolve(ident.owner_id)
    except Exception as exc:  # store failure → fail closed
        logger.error("entitlement resolution failed: %s", type(exc).__name__)
        return False
    if premium:
        await track("entitlement_verified", ident, {"reason": reason})
    return premium


async def usage_for(ident: Identity, cfg: dict) -> dict:
    used = await db.analytics_events.count_documents(
        {"event": "sparks_generated", "owner_type": ident.owner_type, "owner_id": ident.owner_id, "created_at": {"$gte": month_start()}}
    )
    reserved = await limiter.free_used(ident.owner_type, ident.owner_id)
    return {"used": max(used, reserved), "limit": cfg["free_spark_limit"]}


def serialize_spark(s: dict, saved_ids: set[str] | None = None) -> dict:
    out = {k: v for k, v in s.items() if k not in ("_id", "owner_type", "owner_id")}
    out["created_at"] = iso(s.get("created_at"))
    out["completed_at"] = iso(s.get("completed_at"))
    out["saved"] = s["id"] in saved_ids if saved_ids is not None else s.get("saved", False)
    return out


@api.get("/sparks/usage")
async def spark_usage(ident: Annotated[Identity, Depends(identity)]):
    return await usage_for(ident, await get_config())


def coarse_area(loc: dict) -> str | None:
    lat, lng = loc.get("lat"), loc.get("lng")
    return f"{round(lat, 1)},{round(lng, 1)}" if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) else None


async def refund_once_per_day(ident: Identity, receipt: dict) -> None:
    """Paid calls (Places, Claude) may already have run when generation fails, so failures are refunded at most once
    per identity per day — enough for a genuine glitch, useless for farming free paid work (audit N9)."""
    if await limiter.hit(f"refund:{ident.owner_type}:{ident.owner_id}", 1, timedelta(days=1)):
        await limiter.release(receipt)


@api.post("/sparks/generate")
async def generate(
    data: GenerateIn,
    request: Request,
    ident: Annotated[Identity, Depends(identity)],
    x_premium: Annotated[str | None, Header()] = None,
):
    cfg = await get_config()
    # X-Premium is a client claim and is IGNORED for limits (kept only for analytics). Only server-verified status
    # unlocks the Premium lane. All limits are reserved atomically here, BEFORE any Claude / Google Places call.
    if not cfg.get("features", {}).get("generation_enabled", True):
        raise HTTPException(503, "Spark creation is paused for a moment. Please try again soon.")
    premium_verified = await verified_entitlement(ident, cfg)
    try:
        receipt = await limiter.reserve_generation(ip=client_ip(request), owner_type=ident.owner_type, owner_id=ident.owner_id, premium_verified=premium_verified, cfg=cfg)
    except LimitExceeded as exc:
        await track("generation_rate_limited", ident, {"scope": exc.scope, "premium_claim": x_premium == "1", "premium_verified": premium_verified})
        raise HTTPException(exc.status, exc.message)
    # Server-wide daily ceiling on paid generations (audit N10). Counted after the per-identity checks so blocked
    # traffic doesn't consume it; the identity units just taken are handed back.
    if not await limiter.hit("global:generations", cfg["limits"]["global_generations_daily"], timedelta(days=1)):
        await limiter.release(receipt)
        logger.error("global daily generation ceiling reached")
        raise HTTPException(503, "Spark creation is very busy right now. Please try again later.")

    prefs = await db.user_preferences.find_one({"owner_type": ident.owner_type, "owner_id": ident.owner_id}, NO_ID) or {}
    recent = await db.sparks.find({"owner_type": ident.owner_type, "owner_id": ident.owner_id}, NO_ID).sort("created_at", -1).limit(10).to_list(10)
    saved_ids = {d["spark_id"] for d in await db.saved_sparks.find({"owner_type": ident.owner_type, "owner_id": ident.owner_id, "deleted_at": None}, NO_ID).to_list(50)}
    history = {
        "favorite_vibes": prefs.get("favorite_vibes", []),
        "saved_titles": [s["title"] for s in recent if s["id"] in saved_ids],
        "recent_types": [s.get("primary_vibe") for s in recent[:4] if s.get("primary_vibe")],
    }
    try:
        sparks = await generate_sparks(
            relationship_type=data.relationship_type.lower(),
            vibes=data.vibes,
            budget=data.budget,
            distance=data.distance,
            location=data.location,
            exclude_titles=data.exclude_titles + [s["title"] for s in recent],
            history=history,
            date_label=data.date_label,
            time_label=data.time_label,
            occasion=data.occasion,
            surprise=data.surprise,
            ai_settings=cfg.get("ai_settings", {}),
            experience=data.experience_context(),
            venue_hours=cfg.get("features", {}).get("venue_hours", True),
            real_routing=cfg.get("features", {}).get("real_routing", False),
            route_cache=route_cache,
        )
    except Exception:
        logger.exception("Spark generation failed")
        await refund_once_per_day(ident, receipt)
        raise HTTPException(502, "Our Spark engine hit a snag. Please try again.")
    if not sparks:
        await refund_once_per_day(ident, receipt)
        raise HTTPException(404, "We couldn't find the perfect Spark yet.")

    docs = []
    for s in sparks:
        docs.append(
            {
                **s,
                "id": str(uuid.uuid4()),
                "owner_type": ident.owner_type,
                "owner_id": ident.owner_id,
                "relationship_type": data.relationship_type.lower(),
                "vibe": data.vibes,
                "budget": data.budget,
                "distance": data.distance,
                "location": data.location,
                "date_label": data.date_label,
                "time_label": data.time_label,
                "scheduled_at": data.scheduled_at,
                "occasion": data.occasion,
                "surprise": data.surprise,
                "revealed_steps": 1 if data.surprise else len(s.get("activities", [])),
                "fully_revealed_at": None,
                # Experience Engine foundation fields (additive)
                "experience_type": data.resolved_experience_type(),
                "party_size": data.party_size,
                "budget_amount": data.budget_amount,
                "duration_hours": data.duration_hours,
                "interests": data.interests,
                "transport": data.transport,
                "surprise_me": data.surprise_me,
                "status": "generated",
                "share_count": 0,
                "created_at": now(),
                "completed_at": None,
                "deleted_at": None,
            }
        )
    await db.sparks.insert_many(docs)
    await track(
        "sparks_generated",
        ident,
        # No free text or precise location in analytics (audit N13): occasion → flag, location → ~10 km grid cell.
        {"relationship_type": data.relationship_type.lower(), "vibes": data.vibes, "budget": data.budget, "distance": data.distance, "area": coarse_area(data.location), "has_occasion": bool(data.occasion), "surprise": data.surprise, "experience_type": data.resolved_experience_type(), "surprise_me": data.surprise_me, "titles": [d["title"] for d in docs]},
    )
    usage = await usage_for(ident, cfg)
    return {"sparks": [serialize_spark(d, set()) for d in docs], "usage": usage}


@api.get("/sparks/mine")
async def my_sparks(ident: Annotated[Identity, Depends(identity)]):
    q = {"owner_type": ident.owner_type, "owner_id": ident.owner_id, "deleted_at": None}
    saved_rows = await db.saved_sparks.find({**q}, NO_ID).sort("created_at", -1).to_list(200)
    saved_ids = [r["spark_id"] for r in saved_rows]
    all_mine = await db.sparks.find(q, NO_ID).sort("created_at", -1).to_list(200)
    by_id = {s["id"]: s for s in all_mine}
    # Saved sparks may have been created by someone else (shared) — fetch missing ones
    missing = [sid for sid in saved_ids if sid not in by_id]
    if missing:
        for s in await db.sparks.find({"id": {"$in": missing}}, NO_ID).to_list(200):
            by_id[s["id"]] = s
    saved_set = set(saved_ids)

    def as_seen_by_me(sp: dict) -> dict:
        if sp["owner_type"] == ident.owner_type and sp["owner_id"] == ident.owner_id:
            return {**serialize_spark(sp, saved_set), "is_owner": True}
        return {**viewer_view(sp), "saved": True, "is_owner": False}  # someone else's (shared) spark — audit N2

    return {
        "saved": [as_seen_by_me(by_id[sid]) for sid in saved_ids if sid in by_id],
        "created": [serialize_spark(s, saved_set) for s in all_mine if s.get("status") in ("sparked", "scheduled") and not s.get("completed_at")],
        "completed": [serialize_spark(s, saved_set) for s in all_mine if s.get("completed_at")],
        "recent": [serialize_spark(s, saved_set) for s in all_mine[:6]],
    }


# Engine output fields (Increment 1 data, Increment 4 UI) — additive; older sparks simply lack them.
OUTPUT_FIELDS = ("travel_legs", "total_travel_minutes", "total_travel_miles", "total_estimated_cost", "per_person_cost", "priced_stops", "unpriced_stops", "complete", "hours_summary", "routing_source")
PLAN_INPUT_FIELDS = ("experience_type", "party_size", "budget_amount", "duration_hours", "transport")


def surprise_unlocked(s: dict) -> bool:
    """A surprise plan is visible to the recipient once its scheduled time has passed, the owner has revealed every
    stop (an explicit action, `fully_revealed_at`), or it's completed. The owner's starting state never unlocks it —
    previously a one-stop surprise was "fully revealed" the moment it was created (audit N3)."""
    if not s.get("surprise"):
        return True
    if s.get("completed_at") or s.get("fully_revealed_at"):
        return True
    total = len(s.get("activities") or [])
    if "fully_revealed_at" not in s and total > 1 and s.get("revealed_steps", 0) >= total:  # sparks created before the fix
        return True
    sched = s.get("scheduled_at")
    if sched:
        try:
            dt = datetime.fromisoformat(sched.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return now() >= dt
        except ValueError:
            return False
    return False


def redact_for_recipient(out: dict) -> dict:
    """Recipient of a surprise Spark only learns when/where to meet and the dress code."""
    if not out.get("surprise") or surprise_unlocked(out):
        out["locked_for_recipient"] = False
        return out
    first = (out.get("activities") or [{}])[0]
    out["activities"] = []
    out["description"] = "It’s a surprise. All you need to know is when and where to meet ✨"
    out["why"] = ""
    out["tagline"] = "A mystery plan, just for you"
    out["meet_time"] = first.get("start_time")
    out["meet_place"] = first.get("address") or out.get("location_label")
    out["locked_for_recipient"] = True
    # Experience Output (Increment 4): travel legs / costs would hint at the hidden stops — strip them for locked recipients.
    for k in OUTPUT_FIELDS:
        if k in out:
            out[k] = [] if k == "travel_legs" else None
    return out


# The ONLY fields anyone other than the owner ever receives (audit M1/N2): no owner inputs, raw location or ids.
VIEWER_KEYS = ("id", "title", "emoji", "tagline", "description", "primary_vibe", "vibe_tags", "estimated_cost", "estimated_duration", "activities", "location_label", "date_label", "time_label", "scheduled_at", "lat", "lng", "needs_verification", "surprise", "dress_code", "revealed_steps", "fully_revealed_at", "completed_at", "occasion", *OUTPUT_FIELDS, *PLAN_INPUT_FIELDS)


def viewer_view(s: dict) -> dict:
    out = {k: s.get(k) for k in VIEWER_KEYS}
    out["completed_at"] = iso(s.get("completed_at"))
    if "fully_revealed_at" in s:
        out["fully_revealed_at"] = iso(s.get("fully_revealed_at"))
    else:
        out.pop("fully_revealed_at")  # sparks from before the fix: let surprise_unlocked() apply the legacy rule
    return redact_for_recipient(out)


@api.get("/sparks/{spark_id}")
async def get_spark(spark_id: str, ident: Annotated[Identity | None, Depends(identity)] = None):
    s = await db.sparks.find_one({"id": spark_id}, NO_ID)
    if not s:
        raise HTTPException(404, "Spark not found")
    saved = False
    if ident:
        saved = await db.saved_sparks.find_one({"owner_type": ident.owner_type, "owner_id": ident.owner_id, "spark_id": spark_id, "deleted_at": None}) is not None
        await track("spark_viewed", ident, {"spark_id": spark_id, "title": s["title"]})
    is_owner = bool(ident and s["owner_type"] == ident.owner_type and s["owner_id"] == ident.owner_id)
    out = serialize_spark(s, {spark_id} if saved else set()) if is_owner else {**viewer_view(s), "saved": saved}
    out["is_owner"] = is_owner
    return out


@api.get("/shared/{spark_id}")
async def shared_spark(spark_id: str):
    """Public view for invitation recipients — no account needed, only creator-intended fields."""
    s = await db.sparks.find_one({"id": spark_id}, NO_ID)
    if not s:
        raise HTTPException(404, "Spark not found")
    return viewer_view(s)


@api.put("/sparks/{spark_id}/reveal")
async def reveal_step(spark_id: str, ident: Annotated[Identity, Depends(identity)]):
    s = await db.sparks.find_one({"id": spark_id, "owner_type": ident.owner_type, "owner_id": ident.owner_id}, NO_ID)
    if not s:
        raise HTTPException(404, "Spark not found")
    total = len(s.get("activities", []))
    revealed = min(s.get("revealed_steps", 1) + 1, total)
    sets: dict[str, Any] = {"revealed_steps": revealed}
    if revealed >= total and not s.get("fully_revealed_at"):
        sets["fully_revealed_at"] = now()  # the owner revealed the last stop → the recipient may now see the plan
    await db.sparks.update_one({"id": spark_id}, {"$set": sets})
    await track("surprise_step_revealed", ident, {"spark_id": spark_id, "step": revealed})
    return {"revealed_steps": revealed, "total": total}


@api.post("/sparks/{spark_id}/save")
async def save_spark(spark_id: str, ident: Annotated[Identity, Depends(identity)]):
    if not await db.sparks.find_one({"id": spark_id}):
        raise HTTPException(404, "Spark not found")
    await db.saved_sparks.update_one(
        {"owner_type": ident.owner_type, "owner_id": ident.owner_id, "spark_id": spark_id},
        {"$set": {"deleted_at": None}, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now()}},
        upsert=True,
    )
    await track("spark_saved", ident, {"spark_id": spark_id})
    return {"saved": True}


@api.delete("/sparks/{spark_id}/save")
async def unsave_spark(spark_id: str, ident: Annotated[Identity, Depends(identity)]):
    await db.saved_sparks.update_one(
        {"owner_type": ident.owner_type, "owner_id": ident.owner_id, "spark_id": spark_id},
        {"$set": {"deleted_at": now()}},
    )
    return {"saved": False}


@api.put("/sparks/{spark_id}/schedule")
async def schedule_spark(spark_id: str, data: ScheduleIn, ident: Annotated[Identity, Depends(identity)]):
    res = await db.sparks.update_one(
        {"id": spark_id, "owner_type": ident.owner_type, "owner_id": ident.owner_id},
        {"$set": {"date_label": data.date_label, "time_label": data.time_label, "scheduled_at": data.scheduled_at, "status": "scheduled"}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Spark not found")
    return {"ok": True}


@api.post("/sparks/{spark_id}/share")
async def share_spark(spark_id: str, data: ScheduleIn, ident: Annotated[Identity, Depends(identity)]):
    s = await db.sparks.find_one({"id": spark_id}, NO_ID)
    if not s:
        raise HTTPException(404, "Spark not found")
    updates: dict[str, Any] = {"status": "sparked"}
    if data.date_label is not None:
        updates["date_label"] = data.date_label
    if data.time_label is not None:
        updates["time_label"] = data.time_label
    if data.scheduled_at is not None:
        updates["scheduled_at"] = data.scheduled_at
    if s["owner_type"] == ident.owner_type and s["owner_id"] == ident.owner_id:
        await db.sparks.update_one({"id": spark_id}, {"$set": updates, "$inc": {"share_count": 1}})
    await track("spark_shared", ident, {"spark_id": spark_id, "title": s["title"], "surprise": bool(s.get("surprise"))})
    when = " · ".join(x for x in [data.date_label or s.get("date_label"), data.time_label or s.get("time_label")] if x)
    share_url = data.share_url or f"datespark://spark/{spark_id}"
    if s.get("surprise"):
        first = (s.get("activities") or [{}])[0]
        meet = first.get("address") or s.get("location_label", "")
        lines = ["I’m planning a surprise for us. ✨", "", f"🎁 {s['title']}", f"Meet me: {meet}"]
        if when:
            lines.append(f"When: {when}")
        if s.get("dress_code"):
            lines.append(f"Dress code: {s['dress_code']}")
        lines += ["", "\"Trust me on this one. Want to come with me?\"", "", f"Open your invitation: {share_url}"]
    else:
        lines = ["I found something for us. ✨", "", f"{s['emoji']} {s['title']}", s.get("tagline", "")]
        if s.get("occasion"):
            lines.append(f"For: {s['occasion']}")
        if when:
            lines.append(when)
        lines += [s.get("location_label", ""), "", '"I found something I think we\'d enjoy. Want to come with me?"', "", f"See the plan: {share_url}"]
    return {"invitation": "\n".join(l for l in lines if l is not None), "share_url": share_url, "when": when}


@api.post("/sparks/{spark_id}/complete")
async def complete_spark(spark_id: str, ident: Annotated[Identity, Depends(identity)]):
    res = await db.sparks.update_one(
        {"id": spark_id, "owner_type": ident.owner_type, "owner_id": ident.owner_id},
        {"$set": {"completed_at": now(), "status": "completed"}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Spark not found")
    await track("spark_completed", ident, {"spark_id": spark_id})
    return {"ok": True}


# ---------------------------------------------------------------- analytics
@api.post("/events")
async def post_event(data: EventIn, ident: Annotated[Identity, Depends(identity)]):
    await track(data.event, ident, data.props)
    return {"ok": True}


# ---------------------------------------------------------------- admin
async def top_values(field_path: str, unwind: bool = False, limit: int = 5) -> list[dict]:
    pipeline: list[dict] = [{"$match": {"event": "sparks_generated", f"props.{field_path}": {"$exists": True, "$ne": None}}}]
    if unwind:
        pipeline.append({"$unwind": f"$props.{field_path}"})
    pipeline += [{"$group": {"_id": f"$props.{field_path}", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": limit}]
    rows = await db.analytics_events.aggregate(pipeline).to_list(limit)
    return [{"label": str(r["_id"]), "count": r["count"]} for r in rows]


@api.get("/admin/stats")
async def admin_stats(_: Annotated[dict, Depends(require_admin)]):
    cfg = await get_config()
    total_users = await db.users.count_documents({"deleted_at": None})
    since = now() - timedelta(days=30)
    active_users = len(await db.analytics_events.distinct("owner_id", {"created_at": {"$gte": since}}))
    premium = await db.users.count_documents({"deleted_at": None, "subscription_status": "premium"})
    trial = await db.users.count_documents({"deleted_at": None, "subscription_status": "trial"})
    generated = await db.analytics_events.count_documents({"event": "sparks_generated"})
    saved = await db.analytics_events.count_documents({"event": "spark_saved"})
    shared = await db.analytics_events.count_documents({"event": "spark_shared"})
    completed = await db.analytics_events.count_documents({"event": "spark_completed"})
    generators = len(await db.analytics_events.distinct("owner_id", {"event": "sparks_generated"}))
    sharers = len(await db.analytics_events.distinct("owner_id", {"event": "spark_shared"}))
    return {
        "total_users": total_users,
        "active_users": active_users,
        "sparks_generated": generated,
        "sparks_saved": saved,
        "sparks_shared": shared,
        "sparks_completed": completed,
        # Self-reported by the client app (device-side RevenueCat entitlement); not authoritative billing data.
        "premium_subscribers": premium,
        "trial_users": trial,
        "mrr": round(premium * cfg["premium_price"], 2),
        "conversion_rate": round((premium / total_users) * 100, 1) if total_users else 0.0,
        "subscription_metrics_source": "self_reported",
        # Server-verified (RevenueCat webhooks / read-only lookups) — authoritative once server_entitlements is ON.
        "verified_premium_users": await db.entitlements.count_documents({"active": True, "$or": [{"expires_at": None}, {"expires_at": {"$gt": now()}}]}),
        "last_webhook_at": iso(((await db.webhook_events.find_one({}, {"_id": 0, "received_at": 1}, sort=[("received_at", -1)])) or {}).get("received_at")),
        "webhooks_rejected_30d": await db.analytics_events.count_documents({"event": "revenuecat_webhook_rejected", "created_at": {"$gte": since}}),
        "grace_grants_30d": await db.analytics_events.count_documents({"event": "entitlement_verified", "props.reason": {"$regex": "^grace"}, "created_at": {"$gte": since}}),
        "server_entitlements": {"flag": cfg["features"].get("server_entitlements", False), **rc_settings.status()},
        "rate_limited_requests": await db.analytics_events.count_documents({"event": "generation_rate_limited", "created_at": {"$gte": since}}),
        "generate_to_share_rate": round((sharers / generators) * 100, 1) if generators else 0.0,
        "popular_relationships": await top_values("relationship_type"),
        "popular_vibes": await top_values("vibes", unwind=True),
        "popular_locations": await top_values("area"),
        "popular_experiences": await top_values("titles", unwind=True),
    }


@api.get("/admin/config")
async def admin_config(_: Annotated[dict, Depends(require_admin)]):
    return await get_config()


@api.put("/admin/config")
async def update_config(data: ConfigUpdate, _: Annotated[dict, Depends(require_admin)]):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    # Feature flags merge key-by-key so toggling one flag never resets the others.
    features = updates.pop("features", None) or {}
    updates.update({f"features.{k}": v for k, v in features.items()})
    limits = updates.pop("limits", None) or {}
    updates.update({f"limits.{k}": v for k, v in limits.items() if k in DEFAULT_LIMITS and isinstance(v, int) and v >= 0})
    if updates:
        await db.app_config.update_one({"key": "main"}, {"$set": updates}, upsert=True)
    return await get_config()


@api.get("/healthz")
async def healthz():
    """Liveness + database reachability for the load balancer / uptime checks (no auth, no secrets)."""
    try:
        await asyncio.wait_for(db.command("ping"), timeout=2)
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"ok": True}


@api.get("/")
async def root():
    return {"app": "Date Spark ✨", "tagline": "Create the moment."}


@api.get("/admin/ip-check")
async def admin_ip_check(request: Request, _: Annotated[dict, Depends(require_admin)]):
    """Deployment check for the rate limiter: shows how the client address is resolved behind the proxy chain.
    `resolved` must be the caller's public IP (not a load-balancer address) — otherwise set TRUSTED_PROXY_HOPS."""
    return {"resolved": client_ip(request), "x_forwarded_for": request.headers.get("x-forwarded-for"), "cf_connecting_ip": request.headers.get("cf-connecting-ip"), "trusted_proxy_hops": os.environ.get("TRUSTED_PROXY_HOPS", "2")}


# ---------------------------------------------------------------- RevenueCat server-side verification
@api.post("/revenuecat/webhook")
async def revenuecat_webhook(
    request: Request,
    x_revenuecat_webhook_signature: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
):
    """Signed RevenueCat webhook (HMAC over the raw body, 5-minute replay window). Events are persisted once
    (duplicate ids acknowledged, not re-applied) and state is recomputed from the newest data / REST truth, so
    delivery order does not matter. Works independently of the feature flag so state is already correct when the
    flag is turned on; the flag only controls whether `verified_entitlement()` consults that state."""
    raw = await request.body()
    try:
        result = await entitlements.handle_webhook(raw, x_revenuecat_webhook_signature, authorization)
    except SignatureError as exc:
        await track("revenuecat_webhook_rejected", None, {"reason": str(exc)})
        raise HTTPException(401, "Invalid webhook signature")
    except WebhookRetry:
        raise HTTPException(503, "Temporary processing failure; please redeliver")
    await track("revenuecat_webhook_received", None, {k: v for k, v in result.items() if k != "applied"})
    return result


@api.get("/admin/entitlement-check")
async def admin_entitlement_check(user_id: str, _: Annotated[dict, Depends(require_admin)]):
    """Resolved server-side entitlement side-by-side with the self-reported mirror. Read-only; no secrets."""
    return await entitlements.check(user_id)


@api.post("/admin/entitlement-check/{user_id}/reverify")
async def admin_entitlement_reverify(user_id: str, _: Annotated[dict, Depends(require_admin)]):
    """Forced REST lookup for one user (recovery path). 401/403 from RevenueCat surface as 502 and grant nothing."""
    if not await db.users.find_one({"id": user_id, "deleted_at": None}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "User not found")
    try:
        await entitlements.lookup_and_store(user_id)
    except Exception as exc:
        raise HTTPException(502, f"Lookup failed: {getattr(exc, 'kind', type(exc).__name__)}")
    return await entitlements.check(user_id)


class BackfillIn(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=1000, ge=1, le=10000)
    user_ids: Optional[list[str]] = None


@api.post("/admin/entitlements/backfill")
async def admin_entitlement_backfill(_: Annotated[dict, Depends(require_admin)], data: BackfillIn | None = None):
    """Reconcile non-deleted users (all, or `user_ids`) against RevenueCat by exact users.id. Dry run by default
    (report only); `dry_run=false` persists verified state. Aborts (nothing persisted) on auth/permission errors."""
    data = data or BackfillIn()
    return await entitlements.backfill(dry_run=data.dry_run, limit=data.limit, user_ids=data.user_ids)


# ---------------------------------------------------------------- invitation links (outside /api; audit H7)
# EXPO_PUBLIC_SHARE_BASE_URL in the app points at this server's origin. People without the app get a readable page;
# phones with the app open it directly via universal links / App Links (files below).
web = APIRouter()


@web.get("/.well-known/apple-app-site-association")
async def apple_app_site_association():
    app_id = os.environ.get("APPLE_APP_ID")  # "<TEAMID>.<bundle id>"
    if not app_id:
        raise HTTPException(404, "Not configured")
    return {"applinks": {"apps": [], "details": [{"appIDs": [app_id], "components": [{"/": "/s/*"}]}]}}


@web.get("/.well-known/assetlinks.json")
async def android_asset_links():
    package, fingerprints = os.environ.get("ANDROID_PACKAGE"), [f.strip() for f in os.environ.get("ANDROID_SHA256_FINGERPRINTS", "").split(",") if f.strip()]
    if not package or not fingerprints:
        raise HTTPException(404, "Not configured")
    return [{"relation": ["delegate_permission/common.handle_all_urls"], "target": {"namespace": "android_app", "package_name": package, "sha256_cert_fingerprints": fingerprints}}]


def _invite_html(v: dict, spark_id: str) -> str:
    e = html.escape
    store_links = "".join(
        f'<a class="store" href="{e(url)}">{label}</a>'
        for label, url in (("App Store", os.environ.get("APP_STORE_URL")), ("Google Play", os.environ.get("PLAY_STORE_URL")))
        if url
    )
    if v.get("locked_for_recipient"):
        body = f"<p>{e(v.get('description') or '')}</p>"
        if v.get("meet_place") or v.get("meet_time"):
            body += f"<p><b>Meet</b> {e(v.get('meet_time') or '')} {('at ' + e(v.get('meet_place'))) if v.get('meet_place') else ''}</p>"
        if v.get("dress_code"):
            body += f"<p><b>Dress code</b> {e(v['dress_code'])}</p>"
    else:
        stops = "".join(f"<li><b>{e(a.get('start_time') or '')}</b> {e(a.get('activity_name') or '')}{(' — ' + e(a['venue'])) if a.get('venue') else ''}</li>" for a in (v.get("activities") or []))
        body = f"<p>{e(v.get('description') or '')}</p><ol>{stops}</ol>"
    when = " · ".join(x for x in (v.get("date_label"), v.get("time_label")) if x)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{e(v.get('title') or 'Date Spark')}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:24px;background:#FFF9F5;color:#1d1a19;line-height:1.5}}
.open{{display:block;text-align:center;background:#E8456B;color:#fff;padding:14px;border-radius:999px;text-decoration:none;font-weight:700;margin:24px 0 12px}}
.store{{margin-right:16px;color:#E8456B}}</style></head><body>
<p>Date Spark ✨ invitation</p><h1>{e(v.get('emoji') or '')} {e(v.get('title') or '')}</h1><p>{e(v.get('tagline') or '')}</p>
{f'<p><b>When</b> {e(when)}</p>' if when else ''}{body}
<a class="open" href="datespark://spark/{e(spark_id)}">Open in Date Spark</a><p>{store_links}</p></body></html>"""


@web.get("/s/{spark_id}", response_class=HTMLResponse)
async def invite_page(spark_id: str):
    s = await db.sparks.find_one({"id": spark_id}, NO_ID)
    if not s:
        raise HTTPException(404, "This invitation doesn't exist anymore.")
    return HTMLResponse(_invite_html(viewer_view(s), spark_id), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


MAX_BODY_BYTES = 64 * 1024


class BodySizeLimit:
    """Reject request bodies over MAX_BODY_BYTES (declared or streamed) with 413 before the app reads them."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return await self._reject(send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > MAX_BODY_BYTES:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await self._reject(send)

    @staticmethod
    async def _reject(send):
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"detail":"Request body too large"}'})


class _TooLarge(Exception):
    pass


app.include_router(api)
app.include_router(web)
# Auth is a bearer header, never a cookie, so credentials are not needed for CORS (audit M7). Set CORS_ORIGINS
# (comma-separated) to the web app's origin(s) in production; unset keeps the API open to any origin without credentials.
_cors = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()] or ["*"]
# Order matters: the last middleware added is the outermost. CORS must wrap BodySizeLimit so a 413 still carries CORS
# headers (otherwise browsers report an opaque network error instead of "too large").
app.add_middleware(BodySizeLimit)
app.add_middleware(CORSMiddleware, allow_credentials=False, allow_origins=_cors, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Guest-ID", "X-Premium"])
