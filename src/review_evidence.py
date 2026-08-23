"""Canonical evidence for a fresh, independent Fable reviewer (ADR-0137 P5).

A Fable reviewer must judge the same artefact a Classic reviewer would, from a
fresh context. ADR-0137's review boundary says it *"receives canonical
issue/plan/diff/test evidence, never implementer-private context"* — the point
being that a reviewer which can see the implementer's reasoning is no longer
independent of it. It stops reviewing the change and starts reviewing the
argument for the change, and it inherits the implementer's blind spots along
with its conclusions.

**The construction is an ALLOW-LIST, and that is the load-bearing decision.**
:data:`CANONICAL_FIELDS` names everything a reviewer may see; anything else
cannot arrive, because nothing copies it. The alternative — enumerate the
private things and strip them — is fail-open the moment a new field ships:
the field is unknown to the deny-list, so it flows straight through. ADR-0137
condemns exactly that shape in its own tool-surface finding (F2), about a
deny-list of third-party model vendors, and the instruction there is explicit:
*do not reintroduce one as the primary check.* :data:`PRIVATE_MARKERS` below is
a redundant belt over this allow-list, never the primary defence.

Pure by construction: no I/O, no clock, no spawn. The runner that eventually
dispatches a reviewer builds its prompt from a :class:`ReviewEvidence` and can
therefore be tested against a value rather than against a subprocess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from secret_scrub import scrub_secrets

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

__all__ = [
    "CANONICAL_FIELDS",
    "PRIVATE_MARKERS",
    "ReviewEvidence",
    "build_review_evidence",
    "private_markers_in",
]


CANONICAL_FIELDS: frozenset[str] = frozenset(
    {
        # What was asked for.
        "issue_number",
        "issue_title",
        "issue_goal",
        "acceptance_criteria",
        # What was agreed. The plan's OUTCOME, not the planner's transcript.
        "plan_summary",
        # Which exact snapshot the verdict is about. A review of a moved branch
        # is not a review of this change (ADR-0137's bounded-slice rule).
        "branch",
        "base_sha",
        "head_sha",
        # What changed.
        "diff",
        "changed_files",
        # Whether it works. The command and its result, not the runner's log.
        "test_command",
        "test_summary",
        "test_failures",
    }
)
"""Everything a fresh reviewer may see. Nothing else is copied."""


PRIVATE_MARKERS: frozenset[str] = frozenset(
    {
        "implementer_prompt",
        "implementer_transcript",
        "implementer_reasoning",
        "worker_transcript",
        "session_id",
        "spawn_id",
        "gateway_key",
        "account_id",
        "served_model",
        "worktree_path",
        "prior_verdict",
        "review_history",
    }
)
"""A redundant belt, NOT the defence.

Every name here is already unreachable — it is absent from
:data:`CANONICAL_FIELDS`, so nothing copies it. This set exists so that a leak
arriving by some path other than the builder (a caller hand-assembling a
payload, a future field whose *name* is canonical but whose *content* is not)
is still detectable. Treating it as the primary check would reintroduce the
fail-open deny-list the module docstring rejects.
"""


class ReviewEvidence(BaseModel):
    """The whole of a fresh reviewer's input.

    ``extra="forbid"`` is the second half of the allow-list: even a caller that
    constructs this directly, bypassing :func:`build_review_evidence`, cannot
    smuggle a field in. Frozen so an assembled payload cannot be widened after
    the boundary has been crossed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_number: int = Field(ge=1)
    issue_title: str = ""
    issue_goal: str = ""
    acceptance_criteria: tuple[str, ...] = ()

    plan_summary: str = ""

    branch: str = ""
    base_sha: str = ""
    head_sha: str = ""

    diff: str = ""
    changed_files: tuple[str, ...] = ()

    test_command: str = ""
    test_summary: str = ""
    test_failures: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        """The evidence as plain data, for rendering into a prompt.

        Derived from the model's own fields rather than from a hand-written
        list: a field added to the model reaches the prompt, and a field NOT on
        the model cannot, so the two can never disagree.
        """
        return self.model_dump()


def build_review_evidence(source: Mapping[str, Any]) -> ReviewEvidence:
    """Canonical evidence from an arbitrary bundle, copying only what is allowed.

    *source* may carry anything — an implementer's whole result envelope, a
    director's turn record. Only :data:`CANONICAL_FIELDS` are read. Unknown keys
    are not inspected, not logged and not reported: there is nothing to report,
    because a key that is never read cannot leak, and naming it in an error
    would put private content into a message.

    Free text is scrubbed for secrets on the way through. A diff is the most
    likely place for a credential to have been committed by accident, and a
    reviewer is a fresh external process that should never be the thing that
    first sees one.
    """
    picked: dict[str, Any] = {}
    for field in CANONICAL_FIELDS:
        if field not in source:
            continue
        value = source[field]
        if isinstance(value, str):
            value = scrub_secrets(value)
        elif isinstance(value, (list, tuple)):
            value = tuple(scrub_secrets(v) if isinstance(v, str) else v for v in value)
        picked[field] = value
    return ReviewEvidence(**picked)


def private_markers_in(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Private field names present in *payload*, for the belt-level assertion.

    Returns names only, never values: a leak detector that echoes the leak is
    itself a disclosure.
    """
    return tuple(sorted(PRIVATE_MARKERS & set(payload)))
