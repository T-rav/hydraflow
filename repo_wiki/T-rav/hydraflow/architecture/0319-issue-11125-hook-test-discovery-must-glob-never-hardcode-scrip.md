---
id: 0319
topic: architecture
source_issue: 11125
source_phase: plan
created_at: 2026-08-14T11:39:37.484084+00:00
status: active
corroborations: 1
---

# Hook test discovery must glob, never hardcode script names

Shell-script test discovery in `tests/hooks/` must use runtime `glob` over the directory, not an enumerated tuple of filenames.

- Adding a new `tests/hooks/*.sh` should be collected automatically with no registry, list, or Makefile edit.
- An enumerated list silently drifts when scripts are added or removed.

**Why:** Hardcoded lists reproduce the orphan-script problem the gate exists to prevent — new scripts go untested until someone remembers to update the list.
