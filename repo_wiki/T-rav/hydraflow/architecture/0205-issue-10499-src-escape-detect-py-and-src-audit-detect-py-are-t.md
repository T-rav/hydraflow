---
id: 0205
topic: architecture
source_issue: 10499
source_phase: review
created_at: 2026-07-25T06:08:03.278819+00:00
status: stale
corroborations: 1
stale_reason: source issue #10499 closed
---

# src/escape/detect.py and src/audit/detect.py are twin modules — fix both together

`src/audit/detect.py`'s docstring says it mirrors `escape.detect`'s convention: same `_FIELD_SEP`/`_COMMIT_SEP` separators, same raw-`subprocess.run` git-log adapter pattern. A parsing bug found in one is very likely present in the other. PR #10521 (issue #10499) fixed a `_SHA_MARKER` defect in `escape/detect.py` and found + fixed the identical bug in `audit/detect.py` in the same PR rather than deferring it. **Why:** approving a fix in only one twin ships a known-identical bug in the sibling module, guaranteeing a near-immediate follow-up issue.
