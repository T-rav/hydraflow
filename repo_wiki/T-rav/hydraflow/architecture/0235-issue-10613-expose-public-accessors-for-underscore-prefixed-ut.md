---
id: 0235
topic: architecture
source_issue: 10613
source_phase: plan
created_at: 2026-07-26T10:32:19.699666+00:00
status: active
corroborations: 1
---

# Expose public accessors for underscore-prefixed utilities

Do not import underscore-prefixed functions across modules. If `src/secrets_provider/env_provider.py` needs `config._parse_dotenv_text`, add a public accessor to `src/config.py` first.
**Why:** Importing private symbols directly breaks encapsulation and makes refactoring the dotenv parser boundary fragile.
