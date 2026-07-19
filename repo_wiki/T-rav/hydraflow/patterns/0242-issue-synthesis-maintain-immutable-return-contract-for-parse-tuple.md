---
id: 0242
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.226253+00:00
status: active
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
---

# Maintain immutable return contract for `parse()` tuples

Phase result `parse()` must always return `tuple[str, str | None]`; refactors that widen or change this shape break all callers.

Example: Return `("approved", None)` or `("rejected", "reason")` — never a plain `str` or `dict`.

**Why:** Callers destructure the tuple positionally; a shape change produces `TypeError` or silent data corruption at the unpack site.
