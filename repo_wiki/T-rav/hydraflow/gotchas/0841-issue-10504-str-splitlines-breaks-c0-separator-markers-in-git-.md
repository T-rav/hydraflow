---
id: 0841
topic: gotchas
source_issue: 10504
source_phase: plan
created_at: 2026-07-25T02:18:04.061411+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# str.splitlines() breaks C0-separator markers in git log parsing

`escape/detect._added_paths_for_range` parses `git log` output with `str.splitlines()`, which also splits on the `\x1e` byte embedded in `_SHA_MARKER`. The marker line never matches intact, so `CommitInfo.added_paths` is always `()` — silently, with no exception. Downstream, `regression-pin` classification (medium confidence ⇒ CONFIRMED) becomes unreachable dead code and every pin commit falls through to `bug-issue`/low. Fix by splitting on `"\n"` explicitly, or keep control-separator markers free of characters `str.splitlines()` treats as line boundaries (it splits on more than `\n`/`\r`, including `\x1c`–`\x1e`). **Why:** a parser that silently drops data on every call produces a permanently-empty field with no test failure to flag it — the bug hid until the field's downstream consumer (confirmed-escape rate) was audited for staying at 0.00.
