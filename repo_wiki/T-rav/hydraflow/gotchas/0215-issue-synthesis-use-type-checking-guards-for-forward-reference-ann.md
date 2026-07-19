---
id: 0215
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.792430+00:00
status: active
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
---

# Use TYPE_CHECKING guards for forward-reference annotations

Combine `from __future__ import annotations` with `TYPE_CHECKING` guards so forward-reference type imports don't execute at runtime.

Example: `if TYPE_CHECKING: from mymodule import MyType` keeps the symbol available to type checkers while preventing import-time evaluation.

**Why:** Without the guard the symbol is evaluated at import time, creating circular imports or `ImportError` in modules that aren't always available.
