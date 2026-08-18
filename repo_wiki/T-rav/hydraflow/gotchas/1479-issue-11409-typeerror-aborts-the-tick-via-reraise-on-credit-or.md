---
id: 1479
topic: gotchas
source_issue: 11409
source_phase: plan
created_at: 2026-08-18T03:04:36.397163+00:00
status: active
corroborations: 1
---

# TypeError aborts the tick via reraise_on_credit_or_bug, no degradation

Rule: In `src/repo_wiki_loop.py`, `TypeError` is in `LIKELY_BUG_EXCEPTIONS` and is re-raised by `reraise_on_credit_or_bug` at line 441 — it aborts the whole tick, not just the current topic.

Example: A fake signature mismatch does not degrade to a skipped topic; it crashes the tick. When debugging a tick crash, check for signature drift between fakes and reference classes first.

**Why:** Degrading on `TypeError` would mask real bugs in loop logic, so the code treats them as hard failures.
