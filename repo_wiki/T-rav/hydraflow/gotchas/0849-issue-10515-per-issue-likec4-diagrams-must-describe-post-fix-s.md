---
id: 0849
topic: gotchas
source_issue: 10515
source_phase: review
created_at: 2026-07-25T09:50:02.028816+00:00
status: active
corroborations: 1
---

# Per-issue .likec4 diagrams must describe post-fix state, not the bug being fixed

When a PR adds or edits a `.likec4` diagram (e.g. `terminal-bucket-flow.likec4`) alongside a bug fix, the diagram must describe the code as it exists after the fix, not the pre-fix behavior as current present-tense fact — and any cited line range must actually point at the described method.

**Why:** issue #10515 shipped two new diagrams describing the pre-fix bug as current behavior in the very PR that fixed it, plus a line range (435-441) pointing at an unrelated method — misleading for anyone reading the diagram later without the PR context.
