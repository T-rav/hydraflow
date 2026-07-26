---
id: 1222
topic: testing
source_issue: 10616
source_phase: plan
created_at: 2026-07-26T11:05:04.471682+00:00
status: active
corroborations: 1
---

# Widen _ENV_ENUM_OVERRIDES to type[StrEnum] for new enum settings

In `src/config.py` (~line 1023), `_ENV_ENUM_OVERRIDES` maps env vars to enum types. When adding a new `StrEnum`-based config field (e.g. `build_strategy`), widen the override type annotation to `type[StrEnum]` so existing coercions like `queue_strategy` survive the change.

Test that `queue_strategy` env coercion still works after the widening — a too-narrow type annotation silently breaks previously-working enum settings.

**Why:** A type annotation that is too restrictive causes silent regression in env-var coercion for existing enum configs.
