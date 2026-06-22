---
id: 0032
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.317676+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Maintain immutable return contract for `parse()` — `tuple[str, str | None]`

Phase result `parse()` must always return `tuple[str, str | None]`; refactors that widen or change this shape break all callers.

Example: return `("approved", None)` or `("rejected", "reason")` — never a plain `str` or `dict`.

**Why:** Callers destructure the tuple positionally; a shape change produces `TypeError` or silent data corruption at the unpack site.
