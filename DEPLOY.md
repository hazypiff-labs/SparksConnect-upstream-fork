# Deploying Date Spark

## Backend
* Image: `docker build -t datespark-api backend/` — Python 3.12, non-root, JSON logs (`LOG_FORMAT=json`), healthcheck on
  `GET /api/healthz` (pings MongoDB). Two uvicorn workers by default; all shared state (limits, codes, entitlements)
  lives in MongoDB, so scaling out is safe.
* Configuration: every variable is documented in `backend/.env.example`. Required: `MONGO_URL`, `DB_NAME`,
  `JWT_SECRET`, `ANTHROPIC_API_KEY`, `APPLE_AUDIENCES` (if Apple sign-in), `GOOGLE_CLIENT_IDS` (if Google sign-in),
  an email provider (`RESEND_API_KEY` + `EMAIL_FROM`).
* Proxy chain: set `TRUSTED_PROXY_HOPS` to the number of proxies that append to `X-Forwarded-For` (0 when reached
  directly). Only set `TRUST_CF_HEADER=1` when the origin is firewalled to Cloudflare's IP ranges. Verify with
  `GET /api/admin/ip-check` from a phone on mobile data: `resolved` must be that phone's public IP.
* Serve the backend's origin (or proxy `/s/*` and `/.well-known/*` to it) on the domain in
  `EXPO_PUBLIC_SHARE_BASE_URL` so invitation links and universal/App Links work.

## Cost guardrails (do before launch)
* Google Cloud: per-API quotas for Places (Text Search) and Routes, plus a billing budget with alerts.
* Anthropic console: a monthly spend limit for the production key.
* App-level ceilings are admin-tunable in `app_config.limits` (`global_generations_daily`, `places_calls_daily`,
  per-IP / per-identity caps) and `features.generation_enabled` is a kill switch.

## Data
* Backups: nightly `mongodump --uri "$MONGO_URL" --db "$DB_NAME" --gzip --archive=/backups/datespark-$(date +%F).gz`
  with 14-day retention, copied off-host; test a restore into a scratch database monthly.
* Retention: raw analytics events expire after ~13 months (TTL index `analytics_retention`); auth codes and geocode
  cache entries expire automatically.

## Upgrading an existing deployment
No manual data migration is needed; take a `mongodump` first anyway. What existing users will notice:
* **Sessions stay valid.** Tokens issued before this change carry no `tv` claim and users have no `token_version`;
  both read as 0, so nobody is signed out. Rotating `JWT_SECRET` (owner action below) *will* sign everyone out —
  that is intended.
* **Guests keep their data.** Stored guest ids are reused; only new installs get the `g_…` format. The server still
  accepts any 8–64 character id.
* **Google sign-in changes.** The Emergent session exchange (`/api/auth/session`) is gone; old app builds that use
  it get a 404 on Google sign-in and must update. Users created through Emergent have no `google_sub`; their first
  native Google sign-in links to the existing account by (Google-verified) email.
* **Email verification is new.** Existing password accounts start unverified. Nothing is blocked by that, but if a
  verified Google/Apple login arrives for the same email, that provider is trusted with the account: it is linked,
  the password is cleared and old tokens are revoked (prevents account squatting). Users can avoid that by
  verifying from Profile → Verify email.
* **On first start** the server creates new indexes (`auth_codes`, `geocode_cache`, `analytics_retention`,
  `google_sub`) and unsets provider ids on already-deleted accounts. The analytics TTL index deletes events older
  than ~13 months on its first pass — export them first if you need them.
* **Older analytics still hold free text.** Events written before this change keep the location label and occasion
  text. To scrub them now instead of waiting for the TTL:
  `db.analytics_events.updateMany({event: "sparks_generated"}, {$unset: {"props.location": "", "props.occasion": ""}})`.
* **Admin seeding** no longer promotes an existing account to admin; set `ADMIN_EMAIL` to an unused address or
  promote by hand.

## Mobile builds
* `frontend/.env.example` lists the public variables; store identifiers, Maps key and share domain are injected by
  `frontend/app.config.ts` from the EAS profile environment (`frontend/eas.json`).
* Before the first store submission: final `IOS_BUNDLE_ID` / `ANDROID_PACKAGE` (cannot be changed later), a real
  `EXPO_PUBLIC_PRIVACY_URL`, RevenueCat production keys, Google OAuth client ids, `ANDROID_GOOGLE_MAPS_API_KEY`.

## Owner actions that code cannot do
1. **Rotate the leaked credentials**: the admin password and preview URL were committed in `backend/tests/*.py`
   (removed in this branch, still in git history). Change `ADMIN_PASSWORD` on every environment, rotate
   `JWT_SECRET` (signs everyone out), and purge the history (`git filter-repo`) before making the repo public again.
2. RevenueCat: register the webhook (HMAC secret + Authorization value), create the read-only v2 secret key, set
   `REVENUECAT_ENTITLEMENT_ID`, run `POST /api/admin/entitlements/backfill` (dry run, then `dry_run=false`), then turn
   on `features.server_entitlements` — until then paying users get the free quota only.
3. Sign in with Apple `.p8` key (`APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_CLIENT_ID`, `APPLE_PRIVATE_KEY`) so account
   deletion revokes Apple grants (App Store 5.1.1(v)).
4. Google OAuth client ids (iOS / Android / Web) → app env + backend `GOOGLE_CLIENT_IDS`.
5. Email provider account + verified sending domain.
6. Privacy policy + (optional) terms pages; App Store / Play listings referencing them.
