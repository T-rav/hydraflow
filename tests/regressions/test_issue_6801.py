"""Regression test for issue #6801.

``IssueStore.get_pipeline_snapshot`` has a stale docstring that says each stage
maps to "a list of dicts" but the actual return type is
``dict[str, list[PipelineSnapshotEntry]]``.  The docstring also omits the
optional epic metadata keys (``is_epic_child``, ``epic_number``).

These tests inspect the docstring to ensure it accurately describes the typed
return structure and are therefore RED against the current stale docstring.
"""

from __future__ import annotations

import pytest

import inspect

from issue_store import IssueStore


class TestGetPipelineSnapshotDocstring:
    """Docstring for get_pipeline_snapshot must reference PipelineSnapshotEntry."""

    @pytest.mark.xfail(reason="Regression for issue #6801 — fix not yet landed", strict=False)
    def test_docstring_mentions_pipeline_snapshot_entry(self) -> None:
        """The docstring must reference PipelineSnapshotEntry, not 'list of dicts'."""
        docstring = inspect.getdoc(IssueStore.get_pipeline_snapshot)
        assert docstring is not None, "get_pipeline_snapshot must have a docstring"
        assert "PipelineSnapshotEntry" in docstring, (
            f"Docstring should reference PipelineSnapshotEntry but says:\n{docstring}"
        )

    @pytest.mark.xfail(reason="Regression for issue #6801 — fix not yet landed", strict=False)
    def test_docstring_does_not_say_plain_dicts(self) -> None:
        """The docstring must not misleadingly say 'list of dicts'."""
        docstring = inspect.getdoc(IssueStore.get_pipeline_snapshot)
        assert docstring is not None
        assert "list of dicts" not in docstring, (
            f"Docstring still uses the stale 'list of dicts' phrasing:\n{docstring}"
        )

    @pytest.mark.xfail(reason="Regression for issue #6801 — fix not yet landed", strict=False)
    def test_docstring_mentions_epic_metadata(self) -> None:
        """The docstring must mention the optional epic metadata fields."""
        docstring = inspect.getdoc(IssueStore.get_pipeline_snapshot)
        assert docstring is not None
        assert "epic" in docstring.lower(), (
            f"Docstring should mention optional epic metadata but says:\n{docstring}"
        )
