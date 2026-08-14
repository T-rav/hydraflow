---
id: 1330
topic: gotchas
source_issue: 11166
source_phase: plan
created_at: 2026-08-14T19:18:14.572490+00:00
status: active
corroborations: 1
---

# Omit right \b when inflections must match in audit signals

Use `\b` on the left edge only for review/cadence literals in p8 checks. A right `\b` would reject `reviews`, `reviewed`, `reviewing`, and `code-review`, regressing paraphrase tolerance.

Counter-pins in `tests/regressions/test_issue_11166.py` enforce: "Every PR must be reviewed by a fresh-eyes agent" stays PASS.

**Why:** Over-tightening the right edge breaks legitimate paraphrases that issue #11153 established as valid CULTURAL language.
