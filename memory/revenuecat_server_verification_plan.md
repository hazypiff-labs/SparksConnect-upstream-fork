# Plan: Genuine server-side RevenueCat entitlement verification (NOT implemented — for approval)

## Why it is not possible today
Date Spark uses **Emergent-managed RevenueCat**: Emergent holds the OAuth connection to your RevenueCat account and
provisions project/products via its integration proxy. That proxy exposes only `status`, `setup`, `build-config`
and `products`. The managed-integration rules state that pro gating is client-side only — no backend RevenueCat REST
calls, no webhook handlers, no server-enforced premium. Consequently the backend has **no trusted way to ask
"does user X have the `pro` entitlement right now?"**. Phase A therefore protects cost (bounded ceilings, rate
limits) but cannot *verify* Premium.

## What genuine verification needs
| Need | Detail |
|---|---|
| RevenueCat **secret API key** (v1, read‑only scope) | Created in the RevenueCat dashboard → Project → API keys. Stored only as `REVENUECAT_SECRET_KEY` in the backend environment. Used for `GET /v1/subscribers/{app_user_id}` → `subscriber.entitlements.pro.expires_date`. |
| **Webhook** | RevenueCat dashboard → Integrations → Webhooks → URL `https://<backend>/api/revenuecat/webhook`, with an `Authorization` header value you choose (stored as `REVENUECAT_WEBHOOK_SECRET`). Events: INITIAL_PURCHASE, RENEWAL, CANCELLATION, UNCANCELLATION, EXPIRATION, BILLING_ISSUE, PRODUCT_CHANGE, **REFUND / revocation** (`CANCELLATION` with `cancel_reason: CUSTOMER_SUPPORT` and `EXPIRATION`), TRANSFER. |
| Stable app user id | Already true: the app calls `Purchases.logIn(user.id)` on every auth path, so RevenueCat's `app_user_id` == our `users.id`. Guests (anonymous RC ids) cannot be verified → Premium requires an account (the paywall already requires identity). |

## Design (additive, flag `server_entitlements`, default OFF)
1. `backend/entitlements.py`
   - `verify(user_id) -> {active: bool, expires_at, source: "webhook"|"lookup"|"none", checked_at}`.
   - Order: (a) `subscriptions` document maintained by the **webhook** (authoritative, with `expires_at`); (b) if missing/stale (> 24 h) → one REST lookup, cached in the same document; (c) on any failure → `active=False` with `source="none"` (never grants). Legitimate users are protected by the webhook mirror being fresh and by a **grace window**: an entitlement that was active and whose `expires_at` is < 72 h old stays active while verification is unavailable (covers billing retries and outages without granting to never‑paid users).
2. `POST /api/revenuecat/webhook`: constant‑time compare of the `Authorization` header with `REVENUECAT_WEBHOOK_SECRET`, idempotent by event id, writes `subscriptions.{user_id}` = {status, product, expires_at, event, source:"webhook"}. Never trusts anything from the client.
3. `generate`: when the flag is on, `premium = verify(user_id).active` replaces the `X-Premium` hint for signed‑in users; limiter keeps the premium ceilings as a backstop (unchanged). Guests are always free‑tier.
4. `PUT /users/me/subscription` is removed from access decisions entirely (already true) and can later be deleted.
5. Admin stats switch to webhook data: `premium_subscribers`, MRR, conversion become authoritative; `subscription_metrics_source: "revenuecat_webhook"`.

## Migration steps
1. You create the read‑only secret key and the webhook in the RevenueCat dashboard (Emergent cannot do this; it does not affect the managed provisioning, which stays as is).
2. Add `REVENUECAT_SECRET_KEY`, `REVENUECAT_WEBHOOK_SECRET` to the deployment environment (never in chat/logs).
3. Deploy backend with the flag OFF; confirm webhook deliveries arrive (RevenueCat shows delivery status) and `GET /api/admin/entitlement-check?user_id=` (admin‑only) returns the expected state for a test purchaser.
4. Back‑fill: one REST lookup per existing user with `subscription_status != free` (24 users today → negligible).
5. Flip `server_entitlements` ON. Rollback = flag OFF (instant): behaviour returns to Phase A ceilings.

## Costs & limits
- RevenueCat REST v1: included in the plan; rate limit ~ hundreds of requests/min — our lookups are cached 24 h and webhook‑driven, so volume ≈ number of purchases/renewals, not generations.
- No new paid services. Ongoing cost: none beyond the existing RevenueCat plan.

## Risks / trade‑offs
- Leaves the "pure managed" model: you own two RevenueCat secrets and the webhook configuration. Rotating the secret key = update env + redeploy.
- Webhook delivery delay (seconds) after purchase: the app's SDK shows Premium instantly; the server catches up on the first webhook or lookup — the grace/lookup path avoids a false 402 right after purchase.
- Test Store (Expo Go / web preview) purchases are sandbox: webhooks are delivered with `environment: SANDBOX`; the server must accept sandbox events only in non‑production deployments.

## Tests to add
Webhook auth (wrong/missing secret → 401), idempotency, each event type → correct status/expiry, refund/revocation → immediate downgrade, expired entitlement → free quota, lookup failure with fresh webhook data → still premium, lookup failure with no data → free, grace window boundaries, flag OFF → Phase A behaviour, guest → never premium.
