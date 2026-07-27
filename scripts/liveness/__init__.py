"""Tier-1 liveness-kernel decision cores (#10734).

Stdlib-only building blocks for ``scripts/factory_liveness_watchdog.py`` — the
deterministic, LLM-free error kernel that keeps the factory running. Each
module mirrors ``scripts/gates/``: a PURE decision core (fully unit-testable,
no I/O) plus a thin, bounded, failure-tolerant I/O edge.

Nothing in this package may import ``src/`` — a kernel that imports the thing it
watches cannot run when that thing is broken. The contract is pinned by
``tests/architecture/test_liveness_kernel_no_src_imports.py``.
"""

from __future__ import annotations
