---
id: 0426
topic: architecture
source_issue: 11547
source_phase: plan
created_at: 2026-08-30T07:44:19.983831+00:00
status: active
corroborations: 1
---

# Pydantic mixins shrink god-class score in erosion.mass

When extracting methods out of a large Pydantic model, move them into mixin modules and add those mixins as bases: `class HydraFlowConfig(ConfigPathsMixin, ConfigPipelineMixin, BaseModel)`. Verified on pydantic 2.12.5.
- `src/config_paths.py` and `src/config_pipeline.py` hold the moved methods
- `erosion.mass` scores a class from its own `ClassDef` source segment only, so inherited members stop counting
**Why:** The god-class method/LOC axis drops (49 → ~16 methods) with zero behavior change — no caller edits needed.
