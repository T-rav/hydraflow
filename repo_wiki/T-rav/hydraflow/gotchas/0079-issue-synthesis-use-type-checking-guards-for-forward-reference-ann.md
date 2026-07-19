---
id: 0079
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.515075+00:00
status: superseded
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
superseded_by: 0112
---

# Use TYPE_CHECKING guards for forward-reference annotations

Use `from __future__ import annotations` with `TYPE_CHECKING` guards for forward-reference type annotations.

Example: `if TYPE_CHECKING: from mymodule import MyType` keeps the import from executing at runtime.

**Why:** Without the guard the symbol is evaluated at import time, creating circular imports or `ImportError` in modules that aren't always available.
