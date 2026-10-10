# RevenueCat server-side entitlement verification — Rollout Runbook

Implements `/app/memory/revenuecat_server_verification_plan.md` (v3). Built and tested in the development
environment only. **Flag `features.server_entitlements` is OFF.** Nothing in production has been touched.

## What was built (all additive)
| File | Change |
|---|---|
| `backend/entitlements.py` (new) | Settings (env), webhook HMAC verification, REST client (`active_entitlements`), `EntitlementStore` (resolve / webhook pipeline / admin check / backfill) |
| `backend/server.py` | flag default `server_entitlements: False`; `verified_entitlement()` consults the store only when the flag is ON (admin role still always trusted); `POST /api/revenuecat/webhook`; `GET /api/admin/entitlement-check?user_id=`; `POST /api/admin/entitlement-check/{user_id}/reverify`; `POST /api/admin/entitlements/backfill`; admin stats gain `verified_premium_users`, `last_webhook_at`, `webhooks_rejected_30d`, `grace_grants_30d`, `server_entitlements{flag, lookups_configured, webhook_configured, environment, entitlement_id_pinned}`; startup log prints configured yes/no only |
| `backend/tests/test_server_entitlements.py` (new) | 29 tests, RevenueCat HTTP fully stubbed |
| `backend/.env` | dev-only `REVENUECAT_WEBHOOK_SECRET` (dummy signing value for local tests) + `REVENUECAT_ENVIRONMENT=SANDBOX`. No API key → no lookups possible in dev |
| `frontend/app/admin.tsx` | flag row `admin-flag-server-entitlements` (default OFF) |
| New collections | `entitlements` (one doc per `users.id`), `webhook_events` (audit, unique `event_id`) |

Phase A is untouched: `limits.py` still receives only `premium_verified`; `X-Premium` and the self-reported
`PUT /users/me/subscription` mirror are never consulted (re-proven by `test_api_flag_off_vs_on_forged_header_expiry_and_rollback`).

## Environment variables (backend)
| Variable | Secret? | Purpose |
|---|---|---|
| `REVENUECAT_SECRET_KEY` | **yes** | API v2 secret key, project-scoped, single permission `customer_information:customers:read`. Unset = lookups disabled (webhook state only; nothing granted on first sight). |
| `REVENUECAT_PROJECT_ID` | no | `proj…` id from the dashboard URL |
| `REVENUECAT_WEBHOOK_SECRET` | **yes** | HMAC signing secret shown once when enabling signing on the webhook |
| `REVENUECAT_WEBHOOK_AUTH` | yes (optional) | Value of the optional `Authorization` header configured on the webhook (defence in depth) |
| `REVENUECAT_ENTITLEMENT_ID` | no (recommended) | `entl…` id of the `pro` entitlement (Project → Entitlements). If unset, any active entitlement counts — fine while the project has exactly one entitlement |
| `REVENUECAT_ENVIRONMENT` | no | `PRODUCTION` (default) or `SANDBOX`. Events from the other environment are stored but never applied. Preview must use `SANDBOX`. |

Enter them only through the deployment panel's environment variables. Never in the repo, chat, logs, or admin UI.

## Policy summary (as implemented)
- Identity: `app_user_id` == `users.id` exactly; ids not present in `users` with `deleted_at: null` get state nowhere (audited in `webhook_events.applied_to` as `unknown_user`).
- Webhook: raw-body HMAC-SHA256, `t=…,v1=…`, ±300 s window, constant-time compare → otherwise 401. Duplicate `event.id` → 200 `{duplicate:true}`, not re-applied. Older `event_timestamp_ms` than stored → `stale_event_ignored` (granting events). Access-changing events (CANCELLATION, EXPIRATION, BILLING_ISSUE, TRANSFER, PRODUCT_CHANGE, SUBSCRIPTION_PAUSED) re-fetch REST truth; if REST is unavailable, event semantics apply (refund → inactive now; TRANSFER loser → revoked, gainer → nothing until REST truth).
- Resolve (flag ON, non-admin): no doc / `checked_at` > 24 h / stored active but expired → one REST lookup (5 s timeout). Active iff `pro` present and `expires_at > now` (or RC billing grace). 401/403 → fail closed, logged, no grace. 404 → verified not premium. 429/5xx/timeout → stored evidence if still valid; **72 h grace only if last verified state was active and `expires_at` passed < 72 h ago**; otherwise denied. No stored evidence → denied.
- Backfill: iterates non-deleted `users.id` (or a given list), dry run by default, aborts on 401/403 persisting nothing, backs off on 429, 404 = never seen, mismatch list (self-reported vs verified) is report-only.

## Tests
- `tests/test_server_entitlements.py`: **mocked** — every RevenueCat HTTP call is a scripted `RevenueCatClient._get`; webhooks are signed locally with the dev-only secret. Covers: valid/invalid/missing/malformed/stale/future signatures, optional auth header, duplicates, out-of-order, wrong environment, unknown + deleted users, INITIAL_PURCHASE, CANCELLATION (keep-until-expiry and refund), EXPIRATION, BILLING_ISSUE grace, TRANSFER (with and without REST), other-entitlement events, first lookup / 404 / pinned entitlement id, auth errors (no grace), transient errors (grace only for recently-verified-active), stale > 24 h lookup bound, stale-but-valid evidence during outage, error mapping incl. timeout, store outage, backfill abort/dry-run/mismatch/back-off/deleted exclusion, API: flag default OFF + stats redaction, webhook 401/200/duplicate + admin check, **flag OFF vs ON with forged `X-Premium` + forged mirror, expiration → 402, flag OFF rollback** (zero LLM cost), reverify/backfill without key.
- **No RevenueCat sandbox tests were run**: a sandbox webhook requires registering the preview URL in your RevenueCat dashboard and a secret key — both are manual steps for you (below). Nothing was sent to RevenueCat.

## Manual steps (you) — nothing here was done by the agent
1. RevenueCat dashboard → Project → **API keys** → New secret key (v2), permission **only** `customer_information:customers:read`. Note `proj…` id and the `entl…` id of `pro`.
2. Integrations → **Webhooks** → add webhook: URL `https://<backend-host>/api/revenuecat/webhook`, **enable HMAC signing** (copy the secret once), optional Authorization header, environment Production. Optionally a second Sandbox webhook pointing at the preview backend.
3. Deployment panel → environment variables: set the six variables above (`REVENUECAT_ENVIRONMENT=PRODUCTION` in production). Redeploy. Startup log must show `lookups_configured: True, webhook_configured: True`.
4. Send the dashboard "Send test event" → `GET /api/admin/stats` shows `last_webhook_at`; `webhooks_rejected_30d` stays 0.
5. `POST /api/admin/entitlements/backfill` `{"dry_run": true}` → review `mismatches` (self-reported premium but RevenueCat empty/404 are **not** granted). Then `{"dry_run": false}`.
6. Spot-check `GET /api/admin/entitlement-check?user_id=<a known payer>` → `verified_active_now: true`.
7. Flip `Server Entitlements` ON in the admin dashboard (or `PUT /api/admin/config {"features":{"server_entitlements":true}}`). Watch `grace_grants_30d` and `webhooks_rejected_30d`.

## Rollback (leaves the flag OFF)
1. Admin dashboard → `Server Entitlements` OFF (or `PUT /api/admin/config {"features":{"server_entitlements":false}}`) → Phase A behaviour instantly; the webhook keeps recording harmlessly.
2. Optional: delete the webhook and revoke the secret key in RevenueCat; unset the env vars. `entitlements` / `webhook_events` data can stay (additive) or be dropped.
No migrations to undo; the managed RevenueCat provisioning and the app's purchase flow are untouched.

## Not done / out of scope
- No deployment, no production setting, no RevenueCat dashboard change, no product/price/offering change, no live or sandbox API call.
- Admin "entitlement check" screen in the app (endpoints exist; UI only has the flag row).
