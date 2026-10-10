# Date Spark — Code Review Handoff

Documentation only. Nothing in the app, its configuration, or its tests was changed to produce this file.

## 1. Stack
| Layer | Tech |
|---|---|
| Mobile app | Expo SDK 57 · React Native 0.86 · React 19 · expo-router (file-based routing) · TanStack Query 5 · react-native-purchases 10 (RevenueCat) · yarn 1.22 |
| Backend | Python 3.11 · FastAPI 0.110 · Motor/PyMongo (MongoDB) · PyJWT + bcrypt · httpx · `emergentintegrations` (Claude Sonnet 4.6 via Emergent LLM key) |
| Database | MongoDB (`MONGO_URL`, `DB_NAME`) |
| Tests | pytest + pytest-xdist (`backend/pytest.ini`, 2 workers), 204 tests in `backend/tests/` |

## 2. Directory tree (source only — `node_modules`, `.metro-cache`, `.expo`, `__pycache__` omitted)
```
/app
├── README.md
├── design_guidelines.json             # visual tokens mirrored in frontend/src/theme.ts
├── test_result.md                     # running log of testing-agent communication
├── memory/                            # product + engineering docs
│   ├── PRD.md                         # product requirements & completed increments
│   ├── launch_audit.md
│   ├── increment5_plan.md
│   ├── routing_activation_checklist.md
│   ├── revenuecat_server_verification_plan.md   # v3 plan (approved)
│   ├── revenuecat_rollout_runbook.md            # env vars, manual steps, rollout, rollback
│   └── code_review_handoff.md                   # this file
├── test_reports/                      # testing-agent JSON + JUnit XML (iteration_*.json)
├── backend/
│   ├── .env                           # SECRETS — never share (names listed in §6)
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── server.py                      # FastAPI app: models, auth, sparks, admin, config, webhook routes
│   ├── entitlements.py                # RevenueCat server-side verification (webhooks, REST lookups, grace, backfill)
│   ├── limits.py                      # Phase A rate limiting / quotas (atomic Mongo $inc, IP + guest caps)
│   ├── recommend.py                   # LLM prompt building + experience output (timeline, costs)
│   ├── hours.py                       # Google Places opening-hours validation (venue reliability)
│   ├── routing.py                     # travel routing provider abstraction (real_routing flag OFF → estimates)
│   ├── places.py                      # Google Places geocoding
│   └── tests/
│       ├── conftest.py
│       ├── test_datespark_backend.py / test_datespark_iteration2.py
│       ├── test_engine_foundation.py / test_builder_engine_influence.py
│       ├── test_experience_profiles.py / test_experience_builder.py / test_experience_output.py
│       ├── test_venue_hours.py / test_real_routing.py
│       ├── test_phase_a_limits.py / test_iter11_premium_header.py
│       ├── test_server_entitlements.py                 # 29 tests, RevenueCat HTTP mocked
│       └── test_server_entitlements_verification.py    # 15 API-level tests
└── frontend/
    ├── .env                           # EXPO_PUBLIC_* keys + Emergent preview URLs — never share
    ├── app.json · package.json · tsconfig.json · metro.config.js · babel.config.js
    ├── app/                           # expo-router screens
    │   ├── _layout.tsx · index.tsx · +html.tsx
    │   ├── auth.tsx                   # email/password, Google (Emergent-managed), Apple sign-in
    │   ├── premium.tsx                # paywall (RevenueCat offerings)
    │   ├── admin.tsx                  # admin dashboard: stats, config, feature flags, limits
    │   ├── (tabs)/_layout.tsx · home.tsx · create.tsx · sparks.tsx · profile.tsx
    │   ├── create/vibe.tsx · budget.tsx · distance.tsx · when.tsx · results.tsx   # experience builder wizard
    │   ├── spark/[id].tsx             # experience detail (timeline, map, costs, hours badges)
    │   └── share/[id].tsx             # public shared experience
    └── src/
        ├── api.ts                     # fetch wrapper → EXPO_PUBLIC_BACKEND_URL + /api, auth + guest headers
        ├── session.tsx                # auth/session context (JWT, guest id, admin flag)
        ├── revenuecat.tsx             # Purchases SDK init, logIn(user.id), customer-info query, paywall helpers
        ├── features.ts                # feature-flag helpers (reads /api/config/public)
        ├── wizard.tsx · plan.ts · schedule.ts · calendar.ts · constants.ts · query-client.ts
        ├── theme.ts                   # colors/spacing (source of truth for all UI colors)
        ├── components/ SparkCard · Timeline · CostSummary · SparkMap(.web) · ui · error-boundary
        └── utils/storage/             # AsyncStorage / web storage abstraction
```

## 3. Where things live
- **Database models / collections** (`backend/server.py`, Pydantic models near the top): `users` (id, email, role, subscription_status/source, deleted_at), `sparks` (experiences, timeline, travel_legs, hours_summary), `user_preferences`, `app_config` (singleton: features, limits, pricing, AI guidance), `analytics_events`, `rate_limits`/`route_usage`/`route_cache` (limits.py, routing.py), `entitlements` + `webhook_events` (entitlements.py).
- **API endpoints** (all under `/api`): `GET /config/public`, `GET /places/geocode`, auth (`POST /auth/signup`, `/auth/login`, `/auth/session` (Google), `/auth/apple`, `GET /auth/me`, `DELETE /auth/account`), users (`PUT /users/me`, `GET|PUT /users/me/preferences`, `PUT /users/me/subscription` — self-reported mirror, never trusted for limits), sparks (`GET /sparks/usage`, `POST /sparks/generate`, `GET /sparks/mine`, `GET /sparks/{id}`, `GET /shared/{id}`, reveal/save/unsave/schedule/share/complete), `POST /events`, admin (`GET /admin/stats`, `GET|PUT /admin/config`, `GET /admin/ip-check`, `GET /admin/entitlement-check`, `POST /admin/entitlement-check/{user_id}/reverify`, `POST /admin/entitlements/backfill`), `POST /revenuecat/webhook`.
- **Authentication**: JWT bearer tokens (PyJWT, `JWT_SECRET`), bcrypt password hashes, guest identity via `X-Guest-ID`, Emergent-managed Google session exchange, Apple identity-token verification against Apple JWKS (`APPLE_AUDIENCES`). Admin role seeded from `ADMIN_EMAIL`/`ADMIN_PASSWORD`. `require_admin` dependency guards admin routes.
- **Subscriptions / RevenueCat**: client SDK in `frontend/src/revenuecat.tsx` + `app/premium.tsx` (offerings, purchase, restore; `Purchases.logIn(user.id)` so RevenueCat `app_user_id == users.id`). Server side in `backend/entitlements.py`: signed webhook (`X-RevenueCat-Webhook-Signature` HMAC over raw body, ±5 min replay window, duplicate/out-of-order safe), read-only REST lookup (`active_entitlements`, 5 s timeout, 24 h TTL, 401/403 fail closed, 72 h grace only for previously-verified-active users during transient outages), admin reconciliation/backfill. Gated by `features.server_entitlements` (currently **OFF**; OFF == Phase A behaviour). Rate limiting and free/premium lanes: `backend/limits.py`.
- **Configuration**: `backend/.env`, `frontend/.env`, `frontend/app.json` (bundle ids, permissions), `frontend/metro.config.js` (do not modify), `backend/pytest.ini`, `DEFAULT_CONFIG` in `server.py` (feature-flag defaults), `app_config` document (runtime overrides via admin dashboard).

## 4. Running locally
Prereqs: Node 20+ (project uses 24), yarn 1.22, Python 3.11, MongoDB 6+ running locally.
```
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# create backend/.env with the variable NAMES in §6 (your own values)
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# frontend
cd frontend
yarn install
# create frontend/.env with EXPO_PUBLIC_BACKEND_URL=http://localhost:8001 (+ RevenueCat public keys if testing purchases)
yarn expo start          # press w for web, or scan the QR code with Expo Go

# tests (backend must be running on :8001; live-LLM tests need EMERGENT_LLM_KEY)
cd backend && python -m pytest tests -q
```
Notes for a reviewer without keys: the app works without `GOOGLE_PLACES_API_KEY` (hours/geocode degrade gracefully) and without RevenueCat keys (paywall shows but cannot purchase). `POST /sparks/generate` needs `EMERGENT_LLM_KEY` (or swap the LLM call in `recommend.py`).

## 5. Latest changes included
- RevenueCat server-side entitlement verification (`entitlements.py`, webhook + admin endpoints, flag OFF) — see `memory/revenuecat_rollout_runbook.md`.
- Phase A security: client `X-Premium` header ignored, atomic server-side limits, guest-ID rotation + IP caps (`limits.py`).
- Increment 5: venue opening-hours validation (`hours.py`), routing framework stubbed (`routing.py`, `real_routing` OFF).
- Increment 4: experience output (timeline, travel estimates, cost summary).

## 6. Environment variables (names only — values are secrets, never share them)
**backend/.env**: `MONGO_URL`, `DB_NAME`, `EMERGENT_LLM_KEY`, `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `GOOGLE_PLACES_API_KEY`, `APPLE_AUDIENCES`, `REVENUECAT_WEBHOOK_SECRET`, `REVENUECAT_ENVIRONMENT`.
Production-only (not set in dev): `REVENUECAT_SECRET_KEY`, `REVENUECAT_PROJECT_ID`, `REVENUECAT_ENTITLEMENT_ID`, optional `REVENUECAT_WEBHOOK_AUTH`, optional `TRUSTED_PROXY_HOPS`, `ROUTES_DAILY_LIMIT`.
**frontend/.env**: `EXPO_PUBLIC_BACKEND_URL`, `EXPO_PUBLIC_REVENUECAT_IOS_API_KEY`, `EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY`, `EXPO_PUBLIC_REVENUECAT_TEST_API_KEY`, plus Emergent preview plumbing (`EXPO_PACKAGER_PROXY_URL`, `EXPO_PACKAGER_HOSTNAME`, `EXPO_TUNNEL_SUBDOMAIN`, `EXPO_USE_FAST_RESOLVER`, `METRO_CACHE_ROOT`) that a local reviewer should NOT copy.

## 7. Sharing safely
- ⚠️ `backend/.env` and `frontend/.env` are currently **not** listed in `.gitignore` (only `.env*.local` is). Before any ZIP/GitHub share, remove them from the copy you share or add `.env` to `.gitignore` — otherwise `JWT_SECRET`, `EMERGENT_LLM_KEY`, `GOOGLE_PLACES_API_KEY`, `ADMIN_PASSWORD` would be exposed.
- Share via a **private** GitHub repo + collaborator invite; if a secret was ever committed, rotate it (JWT_SECRET invalidates sessions; LLM/Places keys from their dashboards).
- Test credentials in `memory/test_credentials.md` are dev-only; change `ADMIN_PASSWORD` before production.
