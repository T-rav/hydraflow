---
id: 0158
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:34:46.626877+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Maintain immutable return contract for `parse()` — `tuple[str, str | None]`

Phase result `parse()` must always return `tuple[str, str | None]`; refactors that widen or change this shape break all callers.

Example: return `("approved", None)` or `("rejected", "reason")` — never a plain `str` or `dict`.

**Why:** Callers destructure the tuple positionally; a shape change produces `TypeError` or silent data corruption at the unpack site.
