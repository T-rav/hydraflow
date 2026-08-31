---
id: 0424
topic: architecture
source_issue: 11795
source_phase: plan
created_at: 2026-08-30T07:41:57.361398+00:00
status: active
corroborations: 1
---

# Cover docs/standards in CI python path filters

Include `docs/standards/**` in both the `python` filter and the `core_python` brace-glob in `.github/workflows/ci.yml`. Maintain the `core_python ⊆ python` subset invariant using a single brace-glob extension.

**Why:** Load-bearing contract changes to `docs/standards/**` will merge with tests disabled if path filters omit the directory.
