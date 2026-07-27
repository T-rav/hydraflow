---
id: 1377
topic: testing
source_issue: 10747
source_phase: review
created_at: 2026-07-27T23:55:24.611771+00:00
status: active
corroborations: 1
---

# Pin the exact exclusion that makes a fix safe, not just presence

When a test validates remediation guidance, assert both what's present and what's absent — especially when the absence is the safety boundary.

Example: `tests/test_escape_ledger_loop.py::test_low_confidence_body_prescribes_confidence_not_encoding` asserted `--confidence` was present but never pinned that `low` was excluded from the placeholder. Offering `low` would let an operator create an unanswerable resolution row. Add assertions confirming `<high|medium>` is present and `low` is absent in the remediation section.

**Why:** Confirming presence without confirming absence leaves the exact detail that makes the fix safe completely untested.
