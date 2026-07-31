---
id: 1095
topic: patterns
source_issue: 10872
source_phase: plan
created_at: 2026-07-31T05:36:11.799861+00:00
status: active
corroborations: 1
---

# Validate config_overrides names against model_fields, not _real_config_defaults

Validate `config_overrides` field names against `HydraFlowConfig.model_fields`; use `_real_config_defaults()` only for the differs-from-default value check. `_real_config_defaults()` deliberately drops `Path`-typed fields, so name-validation against it wrongly rejects legitimate overrides. **Why:** Conflating the two validation concerns — name validity vs. value differs — produces false rejections on valid `Path`-typed fields like `plans_dir`.
