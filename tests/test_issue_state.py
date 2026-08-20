"""Tests for the issue-state vocabulary owner (#11458).

``issue_state_is_resolved`` is the single predicate deciding which
``PRPort.get_issue_state`` values count as closed. Before #11458 the
membership set was inlined independently at four call sites — two of which
defensively listed the raw REST ``CLOSED`` value that
``PRManager.get_issue_state`` normalizes away (a CLOSED issue comes back as
its ``stateReason``, or ``""`` when null). These tests pin the one true
vocabulary: ``COMPLETED`` / ``NOT_PLANNED`` are resolved; everything else —
including garbage reads — is not.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from issue_state import issue_state_is_resolved
from phase_utils import issue_state_is_resolved as reexported_predicate


class TestIssueStateIsResolved:
    def test_completed_is_resolved(self) -> None:
        assert issue_state_is_resolved("COMPLETED") is True

    def test_not_planned_is_resolved(self) -> None:
        assert issue_state_is_resolved("NOT_PLANNED") is True

    def test_open_is_not_resolved(self) -> None:
        assert issue_state_is_resolved("OPEN") is False

    def test_unknown_is_not_resolved(self) -> None:
        assert issue_state_is_resolved("UNKNOWN") is False

    def test_empty_string_is_not_resolved(self) -> None:
        # PRManager maps a CLOSED issue with null stateReason (closed before
        # GitHub tracked reasons) to "" — deliberately NOT resolved, so an
        # old close is never mistaken for a fixed one.
        assert issue_state_is_resolved("") is False

    def test_none_is_not_resolved(self) -> None:
        assert issue_state_is_resolved(None) is False

    def test_raw_rest_closed_is_not_the_port_vocabulary(self) -> None:
        # The raw REST 'CLOSED' value never escapes PRManager.get_issue_state
        # (it is normalized to the stateReason, or '' when null), so it must
        # not read as resolved — two pre-#11458 call sites carried it as a
        # dead member.
        assert issue_state_is_resolved("CLOSED") is False

    def test_port_garbage_object_is_not_resolved(self) -> None:
        # str-coercion contract: an unconfigured mock's MagicMock return
        # reads as NOT resolved, so a garbage read never triggers a
        # closed-state action.
        assert issue_state_is_resolved(MagicMock()) is False

    def test_lowercase_port_value_is_still_resolved(self) -> None:
        assert issue_state_is_resolved("completed") is True

    def test_phase_utils_reexport_is_the_same_function(self) -> None:
        # #11457's callers import `from phase_utils import
        # issue_state_is_resolved`; the re-export must stay intact.
        assert reexported_predicate is issue_state_is_resolved
