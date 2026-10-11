# Browser end-to-end test (web build + real backend)

Exercises sign-up → email verification → logout → password reset → login, the paywall, invitation links and the
create-a-Spark wizard against the real FastAPI app (Claude replaced by `backend/tests/fake_app.py`, mail kept in the
`email_outbox` collection).

```bash
docker run -d -p 27017:27017 mongo:7
# backend (from backend/)
MONGO_URL=mongodb://127.0.0.1:27017 DB_NAME=sparks_e2e JWT_SECRET=dev ADMIN_EMAIL=admin@example.com \
  ADMIN_PASSWORD=AdminPass123 EMAIL_PROVIDER=outbox APPLE_AUDIENCES=com.test.x \
  PYTHONPATH=. uvicorn tests.fake_app:app --port 28501 &
# web build (from frontend/) — --clear matters: Metro caches inlined EXPO_PUBLIC_* values
EXPO_PUBLIC_BACKEND_URL=http://127.0.0.1:28501 EXPO_PUBLIC_PRIVACY_URL=https://example.com/privacy \
  npx expo export -p web --clear --output-dir /tmp/web-e2e
python3 e2e/spa_server.py /tmp/web-e2e 28502 &
pip install playwright pymongo requests && python e2e/web_e2e.py   # E2E_CHROME=/usr/bin/google-chrome to reuse a local Chrome
```
