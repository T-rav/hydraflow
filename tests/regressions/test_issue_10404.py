"""Regression pin for issue #10404 — ``existing_ids`` scattered across 3 modules.

The erosion sensor (concept-scatter, #10106) flagged that a single merged
change independently introduced ``existing_ids`` in ``audit.store``,
``escape.ledger``, and ``intervention.ledger``. Triage judged this a genuine
Rule-of-Three duplication (byte-identical ``read_all``/``existing_ids``/
``append`` bodies) rather than deliberate parallel structure, and unified the
three into a shared ``JsonlLedger`` base (``jsonl_ledger.py``).

This pins the fix as a *structural* invariant, not just a passing-test
snapshot: each domain ledger must inherit the shared file I/O rather than
re-defining its own copy, so a future edit can't silently re-fork the logic
back into three drifting definitions.
"""

from __future__ import annotations

from audit.store import AuditSampleLedger
from escape.ledger import EscapeLedger
from intervention.ledger import InterventionLedger
from jsonl_ledger import JsonlLedger

_DOMAIN_LEDGERS = (AuditSampleLedger, EscapeLedger, InterventionLedger)
_SHARED_METHODS = ("read_all", "existing_ids", "append")


class TestSingleLedgerDefinition:
    def test_all_domain_ledgers_subclass_jsonl_ledger(self) -> None:
        for cls in _DOMAIN_LEDGERS:
            assert issubclass(cls, JsonlLedger), f"{cls.__name__} must subclass JsonlLedger"

    def test_shared_methods_defined_once_on_the_base_class(self) -> None:
        for method in _SHARED_METHODS:
            assert method in JsonlLedger.__dict__, f"JsonlLedger must define {method}"
            for cls in _DOMAIN_LEDGERS:
                assert method not in cls.__dict__, (
                    f"{cls.__name__} must not redefine {method}; it should be "
                    "inherited from JsonlLedger"
                )
