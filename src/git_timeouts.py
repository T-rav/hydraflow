"""Shared timeout tier for local, read-only git subprocess calls (#10402).

One name, one value, for the adapters that shell out to a local, read-only
``git log`` / ``git diff`` / ``git rev-parse`` (no network) and bound the
call with a generous-but-finite timeout: ``audit.detect``, ``escape.detect``,
``escape_ledger_loop``, ``erosion.spread``, ``erosion.scatter``,
``erosion_metrics_loop``, and ``arch.generators.traceability_matrix``.

Deliberately distinct from two other git timeout tiers that stay put — same
mechanism (a subprocess timeout), different purpose and value, so unifying
them would conflate unrelated bounds:

- ``git_revision._GIT_TIMEOUT_SECS = 5`` — status-endpoint fast-fail; must
  never let a request hang.
- ``principles_audit_loop._GIT_TIMEOUT_SECONDS = 120`` — heavier audit git
  call, pinned by ``tests/regressions/test_issue_9555.py``.
"""

from __future__ import annotations

GIT_READONLY_TIMEOUT_S = 60
