---
id: 0074
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.533252+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Maintain immutable return contract for `parse()` — `tuple[str, str | None]`

Phase result `parse()` must always return `tuple[str, str | None]`; refactors that widen or change this shape break all callers.

Example: return `("approved", None)` or `("rejected", "reason")` — never a plain `str` or `dict`.

**Why:** Callers destructure the tuple positionally; a shape change produces `TypeError` or silent data corruption at the unpack site.
