---
id: 0844
topic: gotchas
source_issue: 10504
source_phase: plan
created_at: 2026-07-25T02:18:04.061465+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# escape.detect fixes have overlapping root causes across #10499/#10498/#10504

`escape/detect._added_paths_for_range`'s splitlines bug is the root cause for both #10504 and #10499, and #10498 separately narrows the `bug-issue` classification via `_fix_subject`. As of this plan neither #10498 nor #10499 has a PR merged. When landing the `added_paths` fix, take only the parser fix (P1) — do not pull in #10498's `_fix_subject` narrowing, and if #10499 merges first, keep only its regression test rather than re-deriving the fix. **Why:** three issues converging on the same module/root cause risk merge races that silently reintroduce the bug (a half-applied marker fix returning `{}` again) unless each PR's scope is deliberately narrowed.
