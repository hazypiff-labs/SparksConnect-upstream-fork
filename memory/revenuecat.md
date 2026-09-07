# RevenueCat — integrated (2026-06)
This file is supposed to serve as a memory to you if you have to interact with user's RevenueCat account via integration proxy at any later point in time.

## Identifiers (from /setup response — copy verbatim)
- rc_project_id: proj3b7b691f
- apple_app_id: app0e83d1764d
- play_app_id: appb1f71feaf0 (package_name updated to com.date_spark.myapp on 2026-06 via idempotent /setup)
- entitlement_lookup_key: pro
- offering_lookup_key: default
- Packages (package -> product_id, current price):
  - $rc_monthly -> prodacfb06a0d6   ($24.99 / P1M, trial: P2W — 2 week free trial)
  - $rc_annual  -> prod935213e5b6   ($79.99 / P1Y, trial: none — default, not surfaced in app UI)
- Dashboard: https://app.revenuecat.com/projects/proj3b7b691f

## Check for project_state in revenuecat status api response. if the project_state is less then project_created, re-fetch RevenueCat playbook via the integration expert tool.
Status check:
`curl -sS -H "$AUTH" "$INTEGRATION_PROXY_URL/internal/revenuecat/projects/e73bca33-58ad-4aec-bbde-10a03cbb1259/status"`

## Later updates to user's products (integration proxy apis ONLY — NEVER call the RevenueCat REST API)
- Change price/duration/trial OR add a package (upsert):
  POST $INTEGRATION_PROXY_URL/internal/revenuecat/projects/e73bca33-58ad-4aec-bbde-10a03cbb1259/products
  body: {"products":[{"package":"$rc_monthly","price":24.99,"currency":"USD","period":"P1M","trial":"P2W","prices":[{"amount_micros":24990000,"currency":"USD"}]}]}
- Remove a package:
  DELETE $INTEGRATION_PROXY_URL/internal/revenuecat/projects/e73bca33-58ad-4aec-bbde-10a03cbb1259/products/%24rc_monthly
- Recover identifiers / repopulate .env: re-run the idempotent /setup call.

## Taking in-app purchases LIVE — store-side steps (USER does these)
Needed ONLY for REAL purchases in published store builds. All steps are in the FAQ section of the payments panel.
- Upload App Store Connect API key (.p8) + Google Play service-account JSON in RevenueCat dashboard
- Create matching IAP products (same product IDs as RevenueCat dashboard) in App Store Connect and Play Console
- Make a release build via Publish, test with TestFlight / internal testing, then submit
