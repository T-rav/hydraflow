---
id: 0012
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.692826+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Use TYPE_CHECKING guards for forward-reference annotations

Use `from __future__ import annotations` with `TYPE_CHECKING` guards for forward-reference type annotations.

Example: `if TYPE_CHECKING: from mymodule import MyType` keeps the import from executing at runtime.

**Why:** Without the guard the symbol is evaluated at import time, creating circular imports or `ImportError` in modules that aren't always available.
