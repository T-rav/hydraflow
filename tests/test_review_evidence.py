"""A fresh reviewer sees canonical evidence and nothing else (ADR-0137 P5)."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

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


#: Every container Pydantic's lax mode accepts for ``tuple[str, ...]``, and the
#: one it accepts for ``str``. The scrub ran on ``str``/``list``/``tuple`` only,
#: so all five arrived at the model untouched. A ``set`` is what a deduplicated
#: changed-files list actually is, and ``bytes`` is what a diff read off an
#: un-texted subprocess pipe actually is; both were confirmed to leak a live
#: token by execution before the fix.
_SECRET = "hfgwctl_" + "b" * 40


@pytest.mark.parametrize(
    ("field", "make_value"),
    [
        ("test_failures", lambda: {f"tok {_SECRET} rejected"}),
        ("changed_files", lambda: frozenset({f"src/{_SECRET}.py"})),
        ("changed_files", lambda: deque([f"src/{_SECRET}.py"])),
        ("changed_files", lambda: (f"src/{_SECRET}.py" for _ in range(1))),
        ("diff", lambda: bytes(f"+TOKEN={_SECRET}\n", "utf-8")),
    ],
    ids=["set", "frozenset", "deque", "generator", "bytes"],
)
def test_a_secret_is_scrubbed_whatever_container_it_arrives_in(
    field: str, make_value: Callable[[], Any]
) -> None:
    """The scrub must cover the shapes Pydantic coerces, not the two it knew.

    Extending an ``isinstance`` tuple would be the same bug one type later, so
    the builder normalises: bytes are decoded, any non-mapping iterable is
    walked, and the leaves are scrubbed.
    """
    # A factory, not a value: a generator built at collection time is consumed
    # by the first run, and a rerun would then scrub an empty tuple and pass.
    payload = build_review_evidence(
        {"issue_number": 1, field: make_value()}
    ).as_payload()
    assert _SECRET not in repr(payload)


def test_a_shape_the_model_refuses_is_still_refused() -> None:
    """The normaliser must not widen what evidence ACCEPTS.

    Walking a ``Mapping`` into a tuple of its keys would have made a ``dict``
    satisfy ``tuple[str, ...]``, which Pydantic rejects today. A scrub that
    quietly admits a new shape is a widening wearing a safety label.
    """
    with pytest.raises(ValidationError):
        build_review_evidence({"issue_number": 1, "changed_files": {"a": 1}})


def test_a_subclass_cannot_render_a_wider_payload() -> None:
    """``extra="forbid"`` stops an extra KEY on this class, not a subclass.

    ``as_payload`` renders ``model_dump()``'s keys, so a subclass declaring one
    more renders one more — the one way an implementer-private field could ride
    the allow-list into the rendered PAYLOAD with every existing test green.
    Not into the prompt: ``build_review_worker_prompt`` indexes payload by
    canonical key name, a second independent allow-list. Saying "prompt" named
    a subject this guard does not protect.
    (Said as *keys*, not as ``model_fields``: they are different sets, and the
    guard was briefly written against the narrower one.)
    """

    class WiderEvidence(ReviewEvidence):
        implementer_transcript: str = ""

    with pytest.raises(ValueError, match="canonical field set"):
        WiderEvidence(issue_number=1).as_payload()


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


# --------------------------------------------------------------------------
# Where each canonical field comes from (#11543)
# --------------------------------------------------------------------------


ISSUE_BODY = """A preamble the ask is not.

## Goal

Bound the cache.

## Acceptance criteria

- A session is evicted at the cap.
- A miss is not a hit.

## Likely surfaces

Everything, apparently.
"""


class TestTheIssueIsReadForItsAskAndNothingElse:
    def test_the_goal_section_is_what_travels(self) -> None:
        from review_evidence import issue_goal_in

        assert issue_goal_in(ISSUE_BODY) == "Bound the cache."

    def test_a_later_section_does_not_travel_with_it(self) -> None:
        """The load-bearing half. Returning the whole body would satisfy "the
        goal is present" while handing a reviewer every argument after it."""
        from review_evidence import issue_goal_in

        assert "Likely surfaces" not in issue_goal_in(ISSUE_BODY)
        assert "A preamble" not in issue_goal_in(ISSUE_BODY)

    def test_a_body_with_no_goal_section_falls_back_to_its_opening(self) -> None:
        from review_evidence import issue_goal_in

        assert issue_goal_in("Just do the thing.\n\n## Notes\n\nlater") == (
            "Just do the thing."
        )

    def test_the_criteria_are_separate_items(self) -> None:
        from review_evidence import acceptance_criteria_in

        assert acceptance_criteria_in(ISSUE_BODY) == (
            "A session is evicted at the cap.",
            "A miss is not a hit.",
        )

    def test_the_criteria_heading_is_matched_case_insensitively(self) -> None:
        # Issue bodies are written by humans and by agents, and the two
        # capitalise differently.
        from review_evidence import acceptance_criteria_in

        assert acceptance_criteria_in("## acceptance criteria\n\n- one\n") == ("one",)

    def test_an_issue_stating_no_criteria_yields_none_rather_than_a_guess(self) -> None:
        """Empty is a real answer. ``build_review_worker_prompt`` tells a
        reviewer to name a missing fact in a finding, so inventing criteria
        from the goal text would be this module deciding what the change was
        for."""
        from review_evidence import acceptance_criteria_in

        assert acceptance_criteria_in("## Goal\n\nsomething\n") == ()

    def test_a_criteria_bullet_is_bounded(self) -> None:
        from review_evidence import MAX_CRITERION_CHARS, acceptance_criteria_in

        body = "## Acceptance criteria\n\n- " + ("x" * (MAX_CRITERION_CHARS * 2))
        assert len(acceptance_criteria_in(body)[0]) == MAX_CRITERION_CHARS


class TestThePlanIsFoundByTheRuleTheClassicReviewerUses:
    def test_the_plan_comment_is_the_one_carrying_the_heading(self) -> None:
        from plan_constants import PLAN_COMMENT_HEADING
        from review_evidence import plan_summary_in

        found = plan_summary_in(
            ["chatter", f"{PLAN_COMMENT_HEADING}\n\n- do the thing", "more chatter"]
        )

        assert found.startswith(PLAN_COMMENT_HEADING)
        assert "chatter" not in found

    def test_no_plan_comment_yields_empty_rather_than_a_neighbour(self) -> None:
        from review_evidence import plan_summary_in

        assert plan_summary_in(["chatter", "more chatter"]) == ""

    def test_the_classic_reviewer_reads_the_same_owned_constant(self) -> None:
        """ "Both presets judge the same artefact" as an identity, not a comment.

        Two spellings of the heading would be two rules that agree until one is
        edited, and the drift is silent in the worse direction: the Fable
        reviewer would find no plan, say so in a finding, and read as a lazy
        reviewer rather than a broken extractor.

        This half is an identity check on the module attribute, because
        ``reviewer._context`` imports the constant at module scope. The other
        half — that ``plan_summary_in`` really consults the shared name rather
        than a copy — is behavioural, below.
        """
        import plan_constants
        from reviewer import _context

        assert _context.PLAN_COMMENT_HEADING is plan_constants.PLAN_COMMENT_HEADING

    def test_moving_the_shared_heading_moves_the_fable_extractor(
        self, monkeypatch: Any
    ) -> None:
        # The behavioural half: ``plan_summary_in`` reads the constant at call
        # time, so a test can move it and watch the extractor follow. A local
        # copy of the literal would survive this.
        import plan_constants
        from review_evidence import plan_summary_in

        monkeypatch.setattr(plan_constants, "PLAN_COMMENT_HEADING", "## Agreed Plan")

        assert plan_summary_in(["## Implementation Plan\n\nold"]) == ""
        assert plan_summary_in(["## Agreed Plan\n\nnew"]).endswith("new")


class TestTheSnapshotIsProvenOrRefused:
    def _reads(self, **overrides: str) -> dict[str, str]:
        base = {
            "status": "# branch.oid " + "a" * 40 + "\n# branch.head agent/issue-7\n",
            "base": "b" * 40 + "\n",
            "diff": "--- a\n+++ b\n",
            "names": "one.py\ntwo.py\n",
        }
        base.update(overrides)
        return base

    def test_a_read_snapshot_names_its_branch_base_and_head(self) -> None:
        from review_evidence import build_review_evidence, canonical_review_source

        evidence = build_review_evidence(
            canonical_review_source(
                issue_number=7,
                issue_title="t",
                issue_body=ISSUE_BODY,
                issue_comments=[],
                reads=self._reads(),
            )
        )

        assert evidence.branch == "agent/issue-7"
        assert evidence.head_sha == "a" * 40
        assert evidence.base_sha == "b" * 40
        assert evidence.changed_files == ("one.py", "two.py")

    def test_a_read_snapshot_is_not_refused(self) -> None:
        # The negative control. Without it, a predicate that answered True
        # unconditionally would pass every assertion below.
        from review_evidence import (
            build_review_evidence,
            canonical_review_source,
            snapshot_is_unreadable,
        )

        evidence = build_review_evidence(
            canonical_review_source(
                issue_number=7,
                issue_title="t",
                issue_body="",
                issue_comments=[],
                reads=self._reads(),
            )
        )

        assert snapshot_is_unreadable(evidence) is False

    @pytest.mark.parametrize("missing", ["status", "base"])
    def test_a_probe_that_did_not_answer_makes_the_snapshot_unreadable(
        self, missing: str
    ) -> None:
        from review_evidence import (
            build_review_evidence,
            canonical_review_source,
            snapshot_is_unreadable,
        )

        evidence = build_review_evidence(
            canonical_review_source(
                issue_number=7,
                issue_title="t",
                issue_body="",
                issue_comments=[],
                reads=self._reads(**{missing: ""}),
            )
        )

        assert snapshot_is_unreadable(evidence) is True

    def test_every_spelling_of_unmeasured_is_covered(self) -> None:
        """#11537's ``unobserved`` and #11542's ``unmeasured`` both mean nobody
        looked, and the predicate compares against the owned SET rather than a
        literal so a third spelling cannot appear without moving that set."""
        from implement_broker import UNMEASURED_TOKENS
        from review_evidence import ReviewEvidence, snapshot_is_unreadable

        for token in UNMEASURED_TOKENS:
            evidence = ReviewEvidence(
                issue_number=1, branch=token, base_sha="x", head_sha="y"
            )
            assert snapshot_is_unreadable(evidence) is True, token

    def test_the_probe_table_extends_the_fences_own_reads(self) -> None:
        """Derived from ``implement_broker.worktree_probes`` rather than
        respelled: a second copy of the porcelain parsing would be a second
        rule free to drift from the one that parses it."""
        from implement_broker import worktree_probes
        from review_evidence import review_probes

        fence = worktree_probes("origin/staging")
        review = review_probes("origin/staging")

        assert review[: len(fence)] == fence
        assert [token for token, _ in review[len(fence) :]] == ["names"]


class TestTheBundleCopiesOnlyWhatIsAllowed:
    def test_private_context_beside_a_canonical_source_does_not_travel(self) -> None:
        # ``canonical_review_source`` has no parameter for it, which is the
        # actual guarantee; this pins that the rendered payload agrees.
        from review_evidence import (
            build_review_evidence,
            canonical_review_source,
            private_markers_in,
        )

        payload = build_review_evidence(
            canonical_review_source(
                issue_number=7,
                issue_title="t",
                issue_body=ISSUE_BODY,
                issue_comments=["## Implementation Plan\n\nagreed"],
                reads={"diff": "--- a\n"},
                test_command="make quality",
            )
        ).as_payload()

        assert private_markers_in(payload) == ()
        assert set(payload) == CANONICAL_FIELDS

    def test_a_secret_in_the_diff_is_scrubbed_on_the_way_through(self) -> None:
        # A reviewer is a fresh external process that must never be the thing
        # that first sees a credential committed by accident.
        from review_evidence import build_review_evidence, canonical_review_source

        evidence = build_review_evidence(
            canonical_review_source(
                issue_number=7,
                issue_title="t",
                issue_body="",
                issue_comments=[],
                reads={"diff": "+token = 'ghp_" + "A" * 36 + "'\n"},
            )
        )

        assert "ghp_" + "A" * 36 not in evidence.diff
