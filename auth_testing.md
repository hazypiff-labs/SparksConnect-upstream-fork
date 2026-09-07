# Sign in with Apple — testing notes
- The native Apple button only renders on iOS when `AppleAuthentication.isAvailableAsync()` is true (real device / simulator with Apple ID; Android & web show email/password only).
- Backend: POST /api/auth/apple {"identity_token": "<jwt>", "name": "...", "email": "..."} verifies against Apple JWKS; audience must be in APPLE_AUDIENCES (bundle id + host.exp.Exponent).
- Invalid/forged token → 401. Wrong `aud` → 401.
- Users are keyed by `apple_sub`; name/email only stored on first sign-in (never overwritten with null).
- Guest Sparks migrate to the user via the X-Guest-ID header, same as email signup.
