---
id: 0836
topic: gotchas
source_issue: 10499
source_phase: plan
created_at: 2026-07-25T01:53:00.854331+00:00
status: stale
corroborations: 1
stale_reason: source issue #10499 closed
---

# escape.detect precedence: revert > regression-pin > hotfix > bug-issue

`_classify` in `src/escape/detect.py` ranks detection sources revert > regression-pin > hotfix > bug-issue; a broken upstream parse can silently downgrade a commit to the lowest tier. A commit adding a `tests/regressions/*.py` file plus a `fix(...)`/closes-`#N` message should classify `regression-pin`/`medium` confidence, not `bug-issue`/`low` — the two confidence tiers matter because only low-confidence output feeds `escape.metrics`' HITL issue filing path.
**Why:** a parse-layer bug (see [[escape_detect_sha_marker_splitlines_bug]]) can make every regression-pin commit misclassify as bug-issue, flooding HITL with issues that medium confidence should have suppressed.
