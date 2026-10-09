import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

import httpx
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr, Field, model_validator

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from places import geocode  # noqa: E402
from recommend import generate_sparks  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("datespark")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
TOKEN_DAYS = 30
password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummy-password-not-used")
NO_ID = {"_id": 0}

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
    "features": {"experience_profiles": True, "experience_builder": True, "experience_output": True},
}

app = FastAPI(title="Date Spark API")
api = APIRouter(prefix="/api")


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- models
class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AppleAuthIn(BaseModel):
    identity_token: str
    name: Optional[str] = Field(default=None, max_length=80)
    email: Optional[EmailStr] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    location: Optional[dict[str, Any]] = None


class PreferencesIn(BaseModel):
    relationship_preferences: list[str] = []
    favorite_vibes: list[str] = []
    budget_preferences: list[str] = []
    distance_preferences: list[str] = []


class SubscriptionSync(BaseModel):
    status: str  # free | trial | premium
    provider: str = "revenuecat"
    renewal_date: Optional[str] = None


class GenerateIn(BaseModel):
    relationship_type: str
    vibes: list[str] = []  # required unless surprise_me (validated below) — legacy requests behave exactly as before
    budget: str
    distance: str
    location: dict[str, Any] = {}
    exclude_titles: list[str] = []
    date_label: Optional[str] = None
    time_label: Optional[str] = None
    occasion: Optional[str] = None
    surprise: bool = False
    # --- Experience Engine foundation (all optional; defaults reproduce the original behaviour) ---
    experience_type: Optional[str] = Field(default=None, max_length=32)  # couple | friends | family | celebration | travel | solo | surprise_me
    party_size: Optional[int] = Field(default=None, ge=1, le=50)
    budget_amount: Optional[float] = Field(default=None, ge=0, le=100000)  # free-form total budget in USD
    duration_hours: Optional[float] = Field(default=None, gt=0, le=24)
    interests: list[str] = Field(default_factory=list, max_length=20)
    transport: Optional[str] = Field(default=None, max_length=16)  # walk | transit | drive
    scheduled_at: Optional[str] = None  # ISO datetime when the experience should start
    surprise_me: bool = False  # engine picks the vibes itself (additive, distinct from `surprise`)

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
    date_label: Optional[str] = None
    time_label: Optional[str] = None
    scheduled_at: Optional[str] = None
    share_url: Optional[str] = None


class SessionIn(BaseModel):
    session_id: str


class EventIn(BaseModel):
    event: str = Field(max_length=64)
    props: dict[str, Any] = {}


class ConfigUpdate(BaseModel):
    free_spark_limit: Optional[int] = Field(default=None, ge=0, le=1000)
    premium_price: Optional[float] = Field(default=None, ge=0)
    trial_days: Optional[int] = Field(default=None, ge=0)
    promo_message: Optional[str] = None
    featured_experiences: Optional[list[dict[str, Any]]] = None
    ai_settings: Optional[dict[str, Any]] = None
    features: Optional[dict[str, bool]] = None


# ---------------------------------------------------------------- identity
def public_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "name": u.get("name", ""),
        "email": u["email"],
        "role": u.get("role", "user"),
        "location": u.get("location"),
        "subscription_status": u.get("subscription_status", "free"),
        "subscription_start": iso(u.get("subscription_start")),
        "subscription_end": iso(u.get("subscription_end")),
        "created_at": iso(u.get("created_at")),
    }


def make_token(user: dict) -> str:
    return jwt.encode(
        {"sub": user["id"], "role": user.get("role", "user"), "iat": now(), "exp": now() + timedelta(days=TOKEN_DAYS)},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


async def user_from_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid or expired token")
    user = await db.users.find_one({"id": claims["sub"], "deleted_at": None}, NO_ID)
    if not user:
        raise HTTPException(401, "User not found")
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
@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.users.create_index("apple_sub", unique=True, sparse=True)
    await db.sparks.create_index([("owner_type", 1), ("owner_id", 1), ("created_at", -1)])
    await db.sparks.create_index("id", unique=True)
    await db.saved_sparks.create_index([("owner_type", 1), ("owner_id", 1), ("spark_id", 1)])
    await db.analytics_events.create_index([("event", 1), ("created_at", -1)])
    admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if admin_email and admin_pw:
        existing = await db.users.find_one({"email": admin_email})
        if not existing:
            await db.users.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "name": "Admin",
                    "email": admin_email,
                    "password_hash": password_hash.hash(admin_pw),
                    "role": "admin",
                    "subscription_status": "premium",
                    "created_at": now(),
                    "deleted_at": None,
                }
            )
        else:
            await db.users.update_one({"email": admin_email}, {"$set": {"role": "admin", "deleted_at": None}})


@app.on_event("shutdown")
async def shutdown():
    client.close()


# ---------------------------------------------------------------- public config
@api.get("/config/public")
async def public_config():
    cfg = await get_config()
    return {k: cfg[k] for k in ("free_spark_limit", "premium_price", "trial_days", "promo_message", "featured_experiences", "features")}


@api.get("/places/geocode")
async def geocode_route(q: str):
    result = await geocode(q.strip())
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


@api.post("/auth/signup")
async def signup(data: SignupIn, x_guest_id: Annotated[str | None, Header()] = None):
    email = data.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "That email is already registered. Try logging in.")
    user = {
        "id": str(uuid.uuid4()),
        "name": data.name.strip(),
        "email": email,
        "password_hash": password_hash.hash(data.password),
        "role": "user",
        "location": None,
        "subscription_status": "free",
        "created_at": now(),
        "deleted_at": None,
    }
    await db.users.insert_one(user)
    await migrate_guest(x_guest_id, user["id"])
    ident = Identity(owner_type="user", owner_id=user["id"])
    await track("signup_completed", ident)
    return {"access_token": make_token(user), "user": public_user(user)}


@api.post("/auth/login")
async def login(data: LoginIn, x_guest_id: Annotated[str | None, Header()] = None):
    user = await db.users.find_one({"email": data.email.lower(), "deleted_at": None}, NO_ID)
    valid = password_hash.verify(data.password, user["password_hash"] if user and user.get("password_hash") else DUMMY_HASH)
    if not user or not user.get("password_hash") or not valid:
        raise HTTPException(401, "Incorrect email or password")
    await migrate_guest(x_guest_id, user["id"])
    return {"access_token": make_token(user), "user": public_user(user)}


@api.get("/auth/me")
async def me(user: Annotated[dict, Depends(require_user)]):
    return public_user(user)


APPLE_JWKS = jwt.PyJWKClient("https://appleid.apple.com/auth/keys", cache_keys=True)
APPLE_AUDIENCES = [a.strip() for a in os.environ.get("APPLE_AUDIENCES", "").split(",") if a.strip()]


@api.post("/auth/session")
async def google_session(data: SessionIn, x_guest_id: Annotated[str | None, Header()] = None):
    """Exchange the one-time Emergent Google Auth session_id for our own JWT."""
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": data.session_id},
            )
    except Exception as exc:
        logger.warning("Emergent auth unreachable: %s", exc)
        raise HTTPException(401, "Google sign-in could not be verified")
    if resp.status_code != 200:
        raise HTTPException(401, "Google sign-in expired or invalid. Please try again.")
    info = resp.json()
    email = (info.get("email") or "").lower()
    if not email:
        raise HTTPException(401, "Google did not return an email")
    user = await db.users.find_one({"email": email, "deleted_at": None}, NO_ID)
    if not user:
        user = {
            "id": str(uuid.uuid4()),
            "name": (info.get("name") or email.split("@")[0]).strip(),
            "email": email,
            "picture": info.get("picture"),
            "google_linked": True,
            "password_hash": None,
            "role": "user",
            "location": None,
            "subscription_status": "free",
            "created_at": now(),
            "deleted_at": None,
        }
        await db.users.insert_one(user)
        await track("signup_completed", Identity(owner_type="user", owner_id=user["id"]), {"provider": "google"})
    else:
        await db.users.update_one({"id": user["id"]}, {"$set": {"google_linked": True, "picture": info.get("picture") or user.get("picture")}})
    await migrate_guest(x_guest_id, user["id"])
    return {"access_token": make_token(user), "session_token": make_token(user), "user": public_user(user)}


@api.post("/auth/apple")
async def apple_login(data: AppleAuthIn, x_guest_id: Annotated[str | None, Header()] = None):
    try:
        signing_key = APPLE_JWKS.get_signing_key_from_jwt(data.identity_token)
        claims = jwt.decode(
            data.identity_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=APPLE_AUDIENCES,
            issuer="https://appleid.apple.com",
        )
    except Exception as exc:
        logger.warning("Apple token rejected: %s", exc)
        raise HTTPException(401, "Apple sign-in could not be verified")
    apple_sub = claims["sub"]
    token_email = (claims.get("email") or data.email or "").lower() or None

    user = await db.users.find_one({"apple_sub": apple_sub, "deleted_at": None}, NO_ID)
    if not user and token_email:
        # Link an existing email/password account with the same verified email.
        user = await db.users.find_one({"email": token_email, "deleted_at": None}, NO_ID)
        if user:
            await db.users.update_one({"id": user["id"]}, {"$set": {"apple_sub": apple_sub}})
    if not user:
        user = {
            "id": str(uuid.uuid4()),
            "name": (data.name or "").strip() or "Spark friend",
            "email": token_email or f"apple-{apple_sub}@apple.local",
            "apple_sub": apple_sub,
            "password_hash": None,
            "role": "user",
            "location": None,
            "subscription_status": "free",
            "created_at": now(),
            "deleted_at": None,
        }
        await db.users.insert_one(user)
        await track("signup_completed", Identity(owner_type="user", owner_id=user["id"]), {"provider": "apple"})
    elif data.name and user.get("name") in (None, "", "Spark friend"):
        await db.users.update_one({"id": user["id"]}, {"$set": {"name": data.name.strip()}})
        user["name"] = data.name.strip()
    await migrate_guest(x_guest_id, user["id"])
    return {"access_token": make_token(user), "user": public_user(user)}


@api.put("/users/me")
async def update_me(data: ProfileUpdate, user: Annotated[dict, Depends(require_user)]):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
    fresh = await db.users.find_one({"id": user["id"]}, NO_ID)
    return public_user(fresh)


@api.delete("/auth/account")
async def delete_account(user: Annotated[dict, Depends(require_user)]):
    # Soft delete: keep records recoverable, remove identifying info.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"deleted_at": now(), "email": f"deleted-{user['id']}@deleted.local", "name": "Deleted user", "location": None}},
    )
    await db.sparks.update_many({"owner_type": "user", "owner_id": user["id"]}, {"$set": {"deleted_at": now()}})
    await db.saved_sparks.update_many({"owner_type": "user", "owner_id": user["id"]}, {"$set": {"deleted_at": now()}})
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
    """Reporting mirror of the store subscription (RevenueCat entitlement is the source of truth on device)."""
    status = data.status if data.status in ("free", "trial", "premium") else "free"
    updates: dict[str, Any] = {"subscription_status": status}
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


async def usage_for(ident: Identity, cfg: dict) -> dict:
    used = await db.analytics_events.count_documents(
        {"event": "sparks_generated", "owner_type": ident.owner_type, "owner_id": ident.owner_id, "created_at": {"$gte": month_start()}}
    )
    return {"used": used, "limit": cfg["free_spark_limit"]}


def serialize_spark(s: dict, saved_ids: set[str] | None = None) -> dict:
    out = {k: v for k, v in s.items() if k not in ("_id", "owner_type", "owner_id")}
    out["created_at"] = iso(s.get("created_at"))
    out["completed_at"] = iso(s.get("completed_at"))
    out["saved"] = s["id"] in saved_ids if saved_ids is not None else s.get("saved", False)
    return out


@api.get("/sparks/usage")
async def spark_usage(ident: Annotated[Identity, Depends(identity)]):
    return await usage_for(ident, await get_config())


@api.post("/sparks/generate")
async def generate(
    data: GenerateIn,
    ident: Annotated[Identity, Depends(identity)],
    x_premium: Annotated[str | None, Header()] = None,
):
    cfg = await get_config()
    usage = await usage_for(ident, cfg)
    is_premium = x_premium == "1"
    if not is_premium and usage["used"] >= usage["limit"]:
        raise HTTPException(402, "You've used this month's free Sparks. Upgrade to Premium for unlimited Sparks.")

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
        )
    except Exception as exc:
        logger.exception("Spark generation failed")
        raise HTTPException(502, f"Our Spark engine hit a snag: {str(exc)[:120]}")
    if not sparks:
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
        {"relationship_type": data.relationship_type.lower(), "vibes": data.vibes, "budget": data.budget, "distance": data.distance, "location": data.location.get("label"), "occasion": data.occasion, "surprise": data.surprise, "experience_type": data.resolved_experience_type(), "surprise_me": data.surprise_me, "titles": [d["title"] for d in docs]},
    )
    usage["used"] += 1
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
    return {
        "saved": [serialize_spark(by_id[sid], saved_set) for sid in saved_ids if sid in by_id],
        "created": [serialize_spark(s, saved_set) for s in all_mine if s.get("status") in ("sparked", "scheduled") and not s.get("completed_at")],
        "completed": [serialize_spark(s, saved_set) for s in all_mine if s.get("completed_at")],
        "recent": [serialize_spark(s, saved_set) for s in all_mine[:6]],
    }


# Engine output fields (Increment 1 data, Increment 4 UI) — additive; older sparks simply lack them.
OUTPUT_FIELDS = ("travel_legs", "total_travel_minutes", "total_travel_miles", "total_estimated_cost", "per_person_cost", "priced_stops", "unpriced_stops", "complete")
PLAN_INPUT_FIELDS = ("experience_type", "party_size", "budget_amount", "duration_hours", "transport")


def surprise_unlocked(s: dict) -> bool:
    """A surprise plan is visible to the recipient once its scheduled time has passed, it's fully revealed, or completed."""
    if not s.get("surprise"):
        return True
    if s.get("completed_at") or s.get("revealed_steps", 0) >= len(s.get("activities", [])):
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


@api.get("/sparks/{spark_id}")
async def get_spark(spark_id: str, ident: Annotated[Identity | None, Depends(identity)] = None):
    s = await db.sparks.find_one({"id": spark_id}, NO_ID)
    if not s:
        raise HTTPException(404, "Spark not found")
    saved = False
    if ident:
        saved = await db.saved_sparks.find_one({"owner_type": ident.owner_type, "owner_id": ident.owner_id, "spark_id": spark_id, "deleted_at": None}) is not None
        await track("spark_viewed", ident, {"spark_id": spark_id, "title": s["title"]})
    out = serialize_spark(s, {spark_id} if saved else set())
    out["is_owner"] = bool(ident and s["owner_type"] == ident.owner_type and s["owner_id"] == ident.owner_id)
    if not out["is_owner"]:
        out = redact_for_recipient(out)
    return out


@api.get("/shared/{spark_id}")
async def shared_spark(spark_id: str):
    """Public view for invitation recipients — no account needed, only creator-intended fields."""
    s = await db.sparks.find_one({"id": spark_id}, NO_ID)
    if not s:
        raise HTTPException(404, "Spark not found")
    keys = ("id", "title", "emoji", "tagline", "description", "primary_vibe", "vibe_tags", "estimated_cost", "estimated_duration", "activities", "location_label", "date_label", "time_label", "scheduled_at", "lat", "lng", "needs_verification", "surprise", "dress_code", "revealed_steps", "completed_at", "occasion", *OUTPUT_FIELDS, *PLAN_INPUT_FIELDS)
    return redact_for_recipient({k: s.get(k) for k in keys})


@api.put("/sparks/{spark_id}/reveal")
async def reveal_step(spark_id: str, ident: Annotated[Identity, Depends(identity)]):
    s = await db.sparks.find_one({"id": spark_id, "owner_type": ident.owner_type, "owner_id": ident.owner_id}, NO_ID)
    if not s:
        raise HTTPException(404, "Spark not found")
    total = len(s.get("activities", []))
    revealed = min(s.get("revealed_steps", 1) + 1, total)
    await db.sparks.update_one({"id": spark_id}, {"$set": {"revealed_steps": revealed}})
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
        "premium_subscribers": premium,
        "trial_users": trial,
        "mrr": round(premium * cfg["premium_price"], 2),
        "conversion_rate": round((premium / total_users) * 100, 1) if total_users else 0.0,
        "generate_to_share_rate": round((sharers / generators) * 100, 1) if generators else 0.0,
        "popular_relationships": await top_values("relationship_type"),
        "popular_vibes": await top_values("vibes", unwind=True),
        "popular_locations": await top_values("location"),
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
    if updates:
        await db.app_config.update_one({"key": "main"}, {"$set": updates}, upsert=True)
    return await get_config()


@api.get("/")
async def root():
    return {"app": "Date Spark ✨", "tagline": "Create the moment."}


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
