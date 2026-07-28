---
id: 0844
topic: gotchas
source_issue: 10504
source_phase: plan
created_at: 2026-07-25T02:18:04.061465+00:00
status: active
corroborations: 1
fixed_in_pr: #10521
code_refs: src/escape/detect.py:_added_paths_for_range,src/escape/detect.py:_fix_subject,src/escape/detect.py:_SHA_MARKER
---

# escape.detect fixes had overlapping root causes across #10499/#10498/#10504 (coordination window closed)

**Spent coordination guidance — the PR-scoping window this entry described is over.** When written, three issues were converging on the same `escape/detect` module: the `_added_paths_for_range` `str.splitlines()` bug was the shared root cause for both #10504 and #10499, and #10498 separately narrowed the `bug-issue` classification via `_fix_subject`. At plan time neither #10498 nor #10499 had a PR merged, so the guidance was — land only the parser fix (P1), do **not** pull in #10498's `_fix_subject` narrowing, and if #10499 merged first keep only its regression test rather than re-deriving the fix — because three PRs on the same module and root cause risked merge races that could silently reintroduce the bug (a half-applied marker fix returning `{}` again).

Both racing issues have since merged, so there is no live coordination decision left to make. #10499 shipped the `escape/detect` marker + parser fix as **#10521** — `src/escape/detect.py:_added_paths_for_range` now parses with `_SHA_MARKER` and an explicit `out.split("\n")` — and #10498 shipped the `_fix_subject` `bug-issue` narrowing as **#10525** (`src/escape/detect.py:_fix_subject`). With every PR in the race landed, this entry is retained only as a historical record of the merge-race hazard, **not** as actionable advice; the scoping instructions above are obsolete.

Retirement provenance (machine-readable — verified by `WikiRotDetectorLoop`'s shipped-claim pass):

```json:entry
{"id": "0844", "rule": "escape-detect-overlapping-root-causes-coordination-window", "topic": "gotchas", "source_issue": 10504, "fixed_in_pr": "#10521", "code_refs": ["src/escape/detect.py:_added_paths_for_range", "src/escape/detect.py:_fix_subject", "src/escape/detect.py:_SHA_MARKER"]}
```

_Coordination window closed by #10521 (issue #10499 — the shared `escape/detect` parser fix) and #10525 (issue #10498 — the `_fix_subject` narrowing). The `code_refs` cite live symbols in `src/escape/detect.py` rather than line numbers because the rot detector resolves symbol cites via AST and deliberately skips a purely-numeric line-tail ref._
