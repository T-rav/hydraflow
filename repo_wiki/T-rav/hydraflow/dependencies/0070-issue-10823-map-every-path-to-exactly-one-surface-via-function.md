---
id: 0070
topic: dependencies
source_issue: 10823
source_phase: plan
created_at: 2026-07-31T00:48:51.333124+00:00
status: active
corroborations: 1
---

# Map every path to exactly one surface via functional_areas.yml + fallback

Use `docs/arch/functional_areas.yml` globs to assign paths to surfaces, with a package-dir fallback for unmatched `src/` paths and `other:<top-dir>` for everything else.

- Glob match → named area.
- Unmatched `src/` → package key.
- Else → `other:<top-dir>`.

No path is ever dropped or assigned to multiple surfaces.

**Why:** Overlapping or dropped surfaces corrupt pair rankings — every path must land in exactly one surface for overlap counts to be meaningful.
