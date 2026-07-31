---
id: 1249
topic: gotchas
source_issue: 10897
source_phase: plan
created_at: 2026-07-31T12:53:03.086114+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Split subject-only from path-verified self-chore predicates

When tightening an exclusion predicate, keep the old signal as a separate public function. `has_self_chore_subject(change)` checks only the commit subject; `is_self_chore_change(change)` now requires subject prefix AND all `changed_paths` within that loop's write scope. A forged `chore(arch):` subject on a PR touching `src/audit/` passes `has_self_chore_subject` but fails `is_self_chore_change`. **Why:** Subject-only signals let attackers forge a maintenance prefix to bypass `sampled_audit_loop` re-audit.
