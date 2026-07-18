---
id: 0113
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.596937+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Use TYPE_CHECKING guards for forward-reference annotations

Use `from __future__ import annotations` with `TYPE_CHECKING` guards for forward-reference type annotations.

Example: `if TYPE_CHECKING: from mymodule import MyType` keeps the import from executing at runtime.

**Why:** Without the guard the symbol is evaluated at import time, creating circular imports or `ImportError` in modules that aren't always available.
