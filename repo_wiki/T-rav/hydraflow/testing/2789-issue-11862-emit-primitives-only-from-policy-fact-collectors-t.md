---
id: 2789
topic: testing
source_issue: 11862
source_phase: plan
created_at: 2026-09-01T03:40:49.615382+00:00
status: active
corroborations: 1
---

# Emit primitives only from policy fact collectors to keep parity tests non-tautological

When adding a `collect_*_facts` collector pinned by a parity test against an existing computation (e.g. `compute_charter_drift`), emit **primitives only** (`present`, `known`, `floor`, `coverage`), never a finding class or a fatal/tolerated boolean. The engine (`_decide_charter` in `python_engine.py`) must re-derive the fatal/tolerated split from `charter_model.NON_FATAL_FINDING_CLASSES` itself. Guard with an explicit assertion that no fact key or value names a finding class.

**Why:** If the collector emits `finding_class` or `fatal`, both the engine and the reference computation read the same pre-derived verdict, and the parity test proves nothing — it passes even when the engine is wrong.
