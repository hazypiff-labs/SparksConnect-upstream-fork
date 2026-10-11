# Date Spark — mobile app (Expo)

```bash
yarn install --frozen-lockfile --ignore-scripts
cp .env.example .env   # fill in values
yarn start             # Expo dev server
yarn typecheck && yarn lint
```

Build-time configuration (store ids, share domain, Maps key) lives in `app.config.ts`; every variable is listed in
`.env.example`. Store builds use the EAS profiles in `eas.json`.
