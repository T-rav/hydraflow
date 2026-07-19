---
id: 0181
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.150881+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Use TYPE_CHECKING guards for forward-reference annotations

Use `from __future__ import annotations` with `TYPE_CHECKING` guards for forward-reference type annotations.

Example: `if TYPE_CHECKING: from mymodule import MyType` keeps the import from executing at runtime.

**Why:** Without the guard the symbol is evaluated at import time, creating circular imports or `ImportError` in modules that aren't always available.
