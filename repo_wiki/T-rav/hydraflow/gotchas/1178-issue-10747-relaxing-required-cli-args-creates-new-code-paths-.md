---
id: 1178
topic: gotchas
source_issue: 10747
source_phase: review
created_at: 2026-07-27T23:55:24.611735+00:00
status: active
corroborations: 1
---

# Relaxing required CLI args creates new code paths—audit predicates

When relaxing a `required=True` CLI argument to optional, audit every downstream predicate that depends on the now-optional value before merging.

Example: `src/escape/resolve.py` relaxed `--encoded-as` from required, admitting `resolve_escape(id, attribution_confidence="low")` with no `encoded_as`. This creates a resolution row that can never satisfy `_surfacing_answered` (which requires `attribution_confidence != "low"`). Since surfacing is one-shot per (id, reason), the HITL issue is permanently stranded. Guard the boundary explicitly — e.g., raise `UnanswerableLowConfidenceError` when `encoded_as is None and attribution_confidence == "low"`.

**Why:** Widening the input boundary without auditing predicates reintroduces the same defect class one layer down — the exact gap the PR intended to fix.
