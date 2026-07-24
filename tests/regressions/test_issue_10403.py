"""Regression pin for issue #10403 — ``append`` scattered across 4 modules.

The concept-scatter sensor (#10106) flagged that a single merged change
independently introduced the ``append`` symbol name across
``src.audit``, ``src.erosion``, ``src.escape``, and ``src.intervention``.
Issue #10404 had already unified three of the four (``AuditSampleLedger``,
``EscapeLedger``, ``InterventionLedger``) onto a shared ``JsonlLedger`` base;
the fourth, ``erosion.trends.TrendStore``, was left out because its rows
(``ChangeDatapoint``) have no stable id to dedup on, so it couldn't subclass
the id-requiring base as-is.

#10403 splits the base into ``AppendOnlyJsonlLedger`` (file I/O only) and
``IdentifiedJsonlLedger`` (adds ``existing_ids()`` dedup) so ``TrendStore``
can join the shared base without gaining a meaningless id-dedup method. This
pins that structural shape: ``TrendStore`` must inherit ``read_all``/
``append`` from ``AppendOnlyJsonlLedger`` rather than re-defining its own
copy, and must NOT gain ``existing_ids`` (it has no id to dedup on).
"""

from __future__ import annotations

from erosion.trends import TrendStore
from jsonl_ledger import AppendOnlyJsonlLedger, IdentifiedJsonlLedger


class TestTrendStoreJoinsSharedBase:
    def test_trend_store_subclasses_append_only_jsonl_ledger(self) -> None:
        assert issubclass(TrendStore, AppendOnlyJsonlLedger), (
            "TrendStore must subclass AppendOnlyJsonlLedger"
        )

    def test_trend_store_does_not_redefine_shared_methods(self) -> None:
        for method in ("read_all", "append"):
            assert method not in TrendStore.__dict__, (
                f"TrendStore must not redefine {method}; it should be "
                "inherited from AppendOnlyJsonlLedger"
            )

    def test_trend_store_has_no_id_based_dedup(self) -> None:
        """``ChangeDatapoint`` has no stable id — ``TrendStore`` must not
        subclass ``IdentifiedJsonlLedger`` or gain ``existing_ids``."""
        assert not issubclass(TrendStore, IdentifiedJsonlLedger)
        assert not hasattr(TrendStore, "existing_ids")
