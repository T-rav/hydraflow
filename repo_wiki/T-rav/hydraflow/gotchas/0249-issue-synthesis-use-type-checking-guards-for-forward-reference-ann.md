---
id: 0249
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.014860+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# Use TYPE_CHECKING guards for forward-reference annotations

Combine `from __future__ import annotations` with `TYPE_CHECKING` guards so forward-reference type imports don't execute at runtime.

Example: `if TYPE_CHECKING: from mymodule import MyType` keeps the symbol available to type checkers while preventing import-time evaluation.

**Why:** Without the guard the symbol is evaluated at import time, creating circular imports or `ImportError` in modules that aren't always available.
