---
id: 0045
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:59:29.446430+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Use TYPE_CHECKING guards for forward-reference annotations

Use `from __future__ import annotations` with `TYPE_CHECKING` guards for forward-reference type annotations.

Example: `if TYPE_CHECKING: from mymodule import MyType` keeps the import from executing at runtime.

**Why:** Without the guard the symbol is evaluated at import time, creating circular imports or `ImportError` in modules that aren't always available.
