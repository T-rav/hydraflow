---
id: 0241
topic: architecture
source_issue: 10622
source_phase: plan
created_at: 2026-07-26T11:28:44.489441+00:00
status: active
corroborations: 1
---

# Drift-exempt artifacts get no min-signal row; shallow clones would red

Do not declare `MIN_SIGNALS` rows for `changelog.md` or `traceability_matrix.md`.

- Both derive from a moving `git log` window and are already `_DRIFT_EXEMPT`
- Shallow CI clones have no history → count is 0 → gate reds spuriously
- `gauntlet-calibration.md` renders `None` by design → use a waiver row citing that

**Why:** A min-signal on a git-history-derived artifact makes the gate fail in every shallow clone, breaking CI for reasons unrelated to the repo's actual structure.
