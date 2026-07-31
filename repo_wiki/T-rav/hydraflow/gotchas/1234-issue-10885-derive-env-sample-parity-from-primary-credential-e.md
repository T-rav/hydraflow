---
id: 1234
topic: gotchas
source_issue: 10885
source_phase: plan
created_at: 2026-07-31T07:40:02.824282+00:00
status: active
corroborations: 1
---

# Derive .env.sample parity from primary CREDENTIAL_ENV_KEYS entries

Every primary (first-listed, index 0) env key in `CREDENTIAL_ENV_KEYS` must appear in `.env.sample`; adding a credential field without a sample entry fails the suite.

- Example: `CREDENTIAL_ENV_KEYS["whatsapp_app_secret"]` primary `HYDRAFLOW_WHATSAPP_APP_SECRET` was missing from `.env.sample` and had to be added.
- Parity is keyed on position 0, not the full priority list.

**Why:** `.env.sample` documents discoverability, not resolution order — coupling it to the full chain would churn the file on every priority tweak.
