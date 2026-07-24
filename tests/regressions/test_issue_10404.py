"""Regression pin for issue #10404 — ``existing_ids`` scattered across 3 modules.

The erosion sensor (concept-scatter, #10106) flagged that a single merged
change independently introduced ``existing_ids`` in ``audit.store``,
``escape.ledger``, and ``intervention.ledger``. Triage judged this a genuine
Rule-of-Three duplication (byte-identical ``read_all``/``existing_ids``/
``append`` bodies) rather than deliberate parallel structure, and unified the
three into a shared ``JsonlLedger`` base (``jsonl_ledger.py``).

Issue #10403 later split that base into ``AppendOnlyJsonlLedger`` (file I/O)
and ``IdentifiedJsonlLedger`` (adds ``existing_ids``) so a fourth, id-less
store (``TrendStore``) could join without gaining a meaningless id-dedup
method — see ``tests/regressions/test_issue_10403.py``. This pin follows that
split: the three id-bearing ledgers now subclass ``IdentifiedJsonlLedger``.

This pins the fix as a *structural* invariant, not just a passing-test
snapshot: each domain ledger must inherit the shared file I/O rather than
re-defining its own copy, so a future edit can't silently re-fork the logic
back into three drifting definitions.
"""

from __future__ import annotations

from audit.store import AuditSampleLedger
from escape.ledger import EscapeLedger
from intervention.ledger import InterventionLedger
from jsonl_ledger import AppendOnlyJsonlLedger, IdentifiedJsonlLedger

_DOMAIN_LEDGERS = (AuditSampleLedger, EscapeLedger, InterventionLedger)
_BASE_METHODS = ("read_all", "append")
_IDENTIFIED_METHODS = ("existing_ids",)


class TestSingleLedgerDefinition:
    def test_all_domain_ledgers_subclass_identified_jsonl_ledger(self) -> None:
        for cls in _DOMAIN_LEDGERS:
            assert issubclass(cls, IdentifiedJsonlLedger), (
                f"{cls.__name__} must subclass IdentifiedJsonlLedger"
            )

    def test_shared_methods_defined_once_on_the_base_classes(self) -> None:
        for method in _BASE_METHODS:
            assert method in AppendOnlyJsonlLedger.__dict__, (
                f"AppendOnlyJsonlLedger must define {method}"
            )
            for cls in _DOMAIN_LEDGERS:
                assert method not in cls.__dict__, (
                    f"{cls.__name__} must not redefine {method}; it should be "
                    "inherited from AppendOnlyJsonlLedger"
                )
        for method in _IDENTIFIED_METHODS:
            assert method in IdentifiedJsonlLedger.__dict__, (
                f"IdentifiedJsonlLedger must define {method}"
            )
            for cls in _DOMAIN_LEDGERS:
                assert method not in cls.__dict__, (
                    f"{cls.__name__} must not redefine {method}; it should be "
                    "inherited from IdentifiedJsonlLedger"
                )
