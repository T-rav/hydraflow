"""A fresh reviewer sees canonical evidence and nothing else (ADR-0137 P5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from review_evidence import (
    CANONICAL_FIELDS,
    PRIVATE_MARKERS,
    ReviewEvidence,
    build_review_evidence,
    private_markers_in,
)


def _implementer_envelope() -> dict[str, object]:
    """A realistic bundle: canonical evidence tangled with private context."""
    return {
        "issue_number": 42,
        "issue_title": "Fix the thing",
        "issue_goal": "The thing should not break",
        "acceptance_criteria": ("it does not break", "a test proves it"),
        "plan_summary": "Change the guard, add a regression",
        "branch": "fix/thing",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "diff": "--- a/src/thing.py\n+++ b/src/thing.py\n+guard()\n",
        "changed_files": ("src/thing.py",),
        "test_command": "make quality",
        "test_summary": "28161 passed",
        "test_failures": (),
        # Everything below is implementer-private and must not survive.
        "implementer_prompt": "You are a HydraFlow implementer...",
        "implementer_transcript": "I considered three approaches and picked...",
        "implementer_reasoning": "the guard felt safer",
        "worker_transcript": "tool_use: Edit ...",
        "session_id": "9f3c2e1a-0000-4000-8000-000000000000",
        "spawn_id": "spawn-7",
        "gateway_key": "hfgw_abcdefgh.0123456789abcdefghij",
        "account_id": "acct-3",
        "served_model": "claude-sonnet-4-6",
        "worktree_path": "/Users/someone/worktrees/thing",
        "prior_verdict": "REQUEST_CHANGES",
        "review_history": "pass 1 found nothing",
    }


def test_only_canonical_fields_survive() -> None:
    payload = build_review_evidence(_implementer_envelope()).as_payload()
    assert set(payload) == CANONICAL_FIELDS


@pytest.mark.parametrize("marker", sorted(PRIVATE_MARKERS))
def test_no_private_field_reaches_the_reviewer(marker: str) -> None:
    payload = build_review_evidence(_implementer_envelope()).as_payload()
    assert marker not in payload


def test_no_private_VALUE_reaches_the_reviewer() -> None:
    """Names are cheap to check; the values are what actually leak."""
    envelope = _implementer_envelope()
    payload = build_review_evidence(envelope).as_payload()
    rendered = repr(payload)
    for key in PRIVATE_MARKERS:
        value = envelope.get(key)
        if isinstance(value, str) and value:
            assert value not in rendered, f"{key}'s VALUE survived into evidence"


def test_an_unknown_field_cannot_leak_by_default() -> None:
    """The allow-list property: a field nobody has heard of is not private-listed.

    A deny-list would pass this bundle straight through, because
    ``surprise_new_context`` is on no list of forbidden names. That is the
    fail-open shape ADR-0137's F2 finding condemns.
    """
    envelope = _implementer_envelope() | {
        "surprise_new_context": "invented after this test was written",
        "another_one": {"nested": "too"},
    }
    payload = build_review_evidence(envelope).as_payload()
    assert "surprise_new_context" not in payload
    assert "another_one" not in payload
    assert "invented after this test was written" not in repr(payload)


def test_the_model_itself_forbids_extra_fields() -> None:
    """Second half of the allow-list: bypassing the builder must not work."""
    with pytest.raises(ValidationError):
        ReviewEvidence(issue_number=1, implementer_transcript="smuggled")


def test_evidence_is_frozen() -> None:
    evidence = build_review_evidence(_implementer_envelope())
    with pytest.raises(ValidationError):
        evidence.issue_goal = "widened after the boundary"


def test_secrets_in_a_diff_are_scrubbed() -> None:
    """A reviewer is a fresh external process; it must not be first to see one."""
    envelope = _implementer_envelope() | {
        "diff": "+GATEWAY_CONTROL_TOKEN=hfgwctl_" + "a" * 40 + "\n"
    }
    payload = build_review_evidence(envelope).as_payload()
    assert "hfgwctl_" + "a" * 40 not in payload["diff"]


def test_secrets_inside_a_sequence_field_are_scrubbed() -> None:
    envelope = _implementer_envelope() | {
        "test_failures": ("token hfgwctl_" + "b" * 40 + " rejected",)
    }
    payload = build_review_evidence(envelope).as_payload()
    assert "hfgwctl_" + "b" * 40 not in payload["test_failures"][0]


def test_missing_canonical_fields_are_absent_not_invented() -> None:
    """A sparse bundle yields empty evidence, never a fabricated snapshot."""
    payload = build_review_evidence({"issue_number": 7}).as_payload()
    assert payload["issue_number"] == 7
    assert payload["diff"] == ""
    assert payload["head_sha"] == ""
    assert payload["acceptance_criteria"] == ()


def test_as_payload_tracks_the_model_not_a_hand_written_list() -> None:
    """The two can never disagree, so a new field cannot be silently unrendered."""
    assert set(ReviewEvidence.model_fields) == CANONICAL_FIELDS


def test_private_markers_are_all_absent_from_the_allow_list() -> None:
    """A name on both lists would be allowed AND flagged — an incoherent rule."""
    assert not (PRIVATE_MARKERS & CANONICAL_FIELDS)


def test_the_belt_reports_names_only() -> None:
    """A leak detector that echoes the leak is itself a disclosure."""
    found = private_markers_in({"spawn_id": "spawn-7", "issue_number": 42})
    assert found == ("spawn_id",)
    assert "spawn-7" not in repr(found)


def test_the_belt_fires_on_a_hand_assembled_payload() -> None:
    """Negative control: the redundant check must actually detect something."""
    assert private_markers_in({"issue_number": 1}) == ()
    assert private_markers_in({"implementer_transcript": "x", "session_id": "y"}) == (
        "implementer_transcript",
        "session_id",
    )
