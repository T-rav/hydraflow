---
id: 0833
topic: gotchas
source_issue: 10498
source_phase: plan
created_at: 2026-07-25T01:51:29.166430+00:00
status: active
corroborations: 1
---

# escape.detect gates bug-issue class on false_close.has_skip_regression

Gate only the `bug-issue` branch of `_classify` in `src/escape/detect.py` on the repo's existing `false_close.has_skip_regression` helper. A commit whose body carries `Skip-Regression:` declares itself behaviour-neutral, so it must not be recorded as a post-merge escape.

- Import the public helper (no leading underscore, per gotchas) rather than copying its regex — it's already the shared P10.6/P10.7 signature and stays pure/git-free.
- Apply the gate only to `bug-issue`: reverts and hotfixes carrying the same trailer must still be recorded as escapes, or the opt-out silences real defects.

**Why:** an over-broad gate above the precedence chain silences real reverts/hotfixes; a copied regex risks drifting from the canonical one.
