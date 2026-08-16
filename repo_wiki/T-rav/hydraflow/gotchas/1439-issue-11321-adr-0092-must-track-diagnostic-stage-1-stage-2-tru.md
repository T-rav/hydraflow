---
id: 1439
topic: gotchas
source_issue: 11321
source_phase: plan
created_at: 2026-08-16T09:00:03.766508+00:00
status: active
corroborations: 1
---

# ADR-0092 must track diagnostic Stage-1/Stage-2 trust boundary

Keep `docs/adr/0092-untrusted-text-trust-boundary.md` updated with the diagnostic read-only / edit-capable split.

Stage-1 consumes issue body / CI-log tail in `repo_root` with `--disallowedTools`; Stage-2 `fix` runs in an isolated worktree with writes enabled.

**Why:** `AdrTouchpointAuditorLoop` fails when ADR text drifts from implementation.
