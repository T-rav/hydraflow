"""Regression: the review-panel rename must keep reading its pre-rename keys.

``ADRCouncilReviewer`` became ``ADRReviewPanel`` so that "Council" names only
the governance layer (#11764). Two of the old names are not internal — they
are already written into artifacts the reviewer reads back on a later cycle:

* ``## Council Amendment Notes`` — the clerk's amendment block, written into
  the ADR *file*. ``docs/adr/0007-dashboard-api-multi-repo-scoping.md`` carries
  one on disk right now.
* ``COUNCIL_RESULT:`` — the header the orchestrator transcript is parsed on.

Dropping either read fails silently rather than loudly: a stale amendment block
is appended beside instead of superseded, and a real verdict is discarded as
NO_CONSENSUS. These tests pin both reads.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from adr_reviewer import ADRReviewPanel
from models import ADRReviewPanelResult, PanelVerdict, PanelVote
from tests.helpers import ConfigFactory


def _make_panel(tmp_path: Path) -> ADRReviewPanel:
    from events import EventBus

    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    return ADRReviewPanel(config, EventBus(), MagicMock())


def _request_changes_result() -> ADRReviewPanelResult:
    return ADRReviewPanelResult(
        adr_number=7,
        adr_title="Dashboard API multi-repo scoping",
        final_decision="REQUEST_CHANGES",
        votes=[
            PanelVote(
                role="editor",
                verdict=PanelVerdict.REQUEST_CHANGES,
                reasoning="Name the fallback explicitly",
            )
        ],
    )


class TestLegacyAmendmentHeading:
    """A pre-rename amendment block is superseded, not duplicated."""

    def test_legacy_block_is_replaced_in_place(self, tmp_path: Path) -> None:
        panel = _make_panel(tmp_path)
        content = (
            "# ADR-0007: Test\n\n"
            "**Status:** Proposed\n\n"
            "## Context\n\nA\n\n"
            "## Decision\n\nB\n\n"
            "## Consequences\n\nC\n\n"
            "## Council Amendment Notes\n\n"
            "- Editor: a note from before the rename\n"
        )

        amended = panel._build_clerk_amendment(content, _request_changes_result())

        # The stale block is gone and exactly one amendment section remains.
        assert "## Council Amendment Notes" not in amended
        assert amended.count("Amendment Notes") == 1
        assert "a note from before the rename" not in amended
        assert "Name the fallback explicitly" in amended

    def test_new_heading_is_also_replaced_in_place(self, tmp_path: Path) -> None:
        panel = _make_panel(tmp_path)
        content = (
            "# ADR-0007: Test\n\n"
            "**Status:** Proposed\n\n"
            "## Context\n\nA\n\n"
            "## Review Panel Amendment Notes\n\n"
            "- Editor: a stale note\n"
        )

        amended = panel._build_clerk_amendment(content, _request_changes_result())

        assert amended.count("Amendment Notes") == 1
        assert "a stale note" not in amended


class TestLegacyTranscriptHeader:
    """A transcript still headed ``COUNCIL_RESULT:`` yields a real verdict."""

    def test_legacy_header_parses_to_a_decision(self, tmp_path: Path) -> None:
        panel = _make_panel(tmp_path)
        transcript = (
            "COUNCIL_RESULT:\n"
            "rounds_needed: 1\n"
            "architect_verdict: APPROVE\n"
            "architect_reasoning: Sound\n"
            "pragmatist_verdict: APPROVE\n"
            "pragmatist_reasoning: Worth it\n"
            "editor_verdict: APPROVE\n"
            "editor_reasoning: Complete\n"
            "final_decision: ACCEPT\n"
            "summary: Unanimous.\n"
        )

        result = panel._parse_panel_result(transcript, 7, "Test")

        assert result.final_decision == "ACCEPT"
        assert result.summary != "Failed to parse review-panel result"
        assert result.approve_count == 3

    def test_current_header_parses_to_a_decision(self, tmp_path: Path) -> None:
        panel = _make_panel(tmp_path)
        transcript = (
            "PANEL_RESULT:\n"
            "rounds_needed: 1\n"
            "architect_verdict: APPROVE\n"
            "architect_reasoning: Sound\n"
            "pragmatist_verdict: APPROVE\n"
            "pragmatist_reasoning: Worth it\n"
            "editor_verdict: APPROVE\n"
            "editor_reasoning: Complete\n"
            "final_decision: ACCEPT\n"
            "summary: Unanimous.\n"
        )

        result = panel._parse_panel_result(transcript, 7, "Test")

        assert result.final_decision == "ACCEPT"
        assert result.approve_count == 3
