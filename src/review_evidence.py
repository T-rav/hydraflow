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

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from secret_scrub import scrub_secrets

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
arriving by some path other than the builder — a caller hand-assembling a
payload — is still detectable. Treating it as the primary check would
reintroduce the fail-open deny-list the module docstring rejects.

It compares **keys**, and only keys. This docstring used to claim a second
catch: "a future field whose *name* is canonical but whose *content* is not".
:func:`private_markers_in` cannot see content and never could, so the clause
described a check that was not there — worse than no clause, because a reader
who trusts it stops looking for the check that would.
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

        Which is exactly why the rendered key set is checked here. A *subclass*
        is the one way an implementer-private field could ride the allow-list
        into the rendered PAYLOAD while every existing test stayed green —
        ``extra="forbid"`` does not stop a subclass, it stops an extra key on
        this class.

        The check is on ``model_dump()``'s **keys**, not on ``model_fields``.
        The first version compared ``model_fields`` and its docstring claimed
        it guarded what got rendered; those are not the same set, and two
        subclass shapes walked straight past it — a ``@computed_field`` (absent
        from ``model_fields``, present in the dump by design) and
        ``ConfigDict(extra="allow")`` (``model_fields`` unchanged, extras
        emitted). Both were confirmed by execution to smuggle
        ``implementer_transcript`` into the payload. A guard that asserts a
        proxy for its subject, over a docstring claiming it asserts the
        subject, is the exact shape this module was repaired for; here it is
        one layer in.

        Note the scope precisely: this guards the PAYLOAD, not the prompt.
        ``build_review_worker_prompt`` indexes the payload by canonical key
        name, so it is a second, independent allow-list and an extra key would
        not reach a reviewer through it. An earlier wording here said "prompt",
        which named a subject this guard does not protect and left the one that
        does protect it stated nowhere.
        """
        payload = self.model_dump()
        rendered = set(payload)
        if rendered != CANONICAL_FIELDS:
            extra = sorted(rendered - CANONICAL_FIELDS)
            missing = sorted(CANONICAL_FIELDS - rendered)
            raise ValueError(
                "review evidence must render exactly the canonical field set; "
                f"{type(self).__name__} adds {extra} and drops {missing}. "
                "Widening what a fresh reviewer sees is a change to "
                "CANONICAL_FIELDS, never a subclass."
            )
        return payload


#: Ceilings on the walk :func:`_scrubbed` performs. Not tuning knobs — they
#: exist because widening the walk from ``list``/``tuple`` to ``Iterable``
#: introduced two ways to not terminate that the narrower version could not
#: have: a ``list`` is always finite and the old code never recursed, so
#: neither an endless generator nor a deeply nested structure was reachable.
#:
#: Both ceilings are far above any legitimate bundle. ``ReviewEvidence``'s
#: sequence fields are ``tuple[str, ...]``, so honest depth is 1 and honest
#: length is "files in a very large PR". Anything past these is a caller
#: handing evidence a stream, not a bundle.
_MAX_SEQUENCE_ITEMS = 50_000
_MAX_NESTING_DEPTH = 8


def _scrubbed(value: Any, _depth: int = 0) -> Any:
    """*value* with every string it carries scrubbed, whatever shape it arrived in.

    The scrub used to run on ``str`` and on ``list``/``tuple``, which is the
    same class of bug one type later. Pydantic's lax mode — which this model
    runs in — coerces a good deal more than that into its fields: ``set``,
    ``frozenset``, ``deque`` and a bare generator all satisfy
    ``tuple[str, ...]``, and ``bytes`` satisfies ``str``. Every one of those
    shapes reached ``ReviewEvidence`` untouched, and both realistic ones leaked
    a live token by execution: a deduplicated changed-files list is a ``set``,
    and a diff read off an un-texted subprocess pipe is ``bytes``.

    So the fix is not a longer ``isinstance`` tuple. It is: decode bytes, walk
    any iterable, and scrub the leaves — which covers the shapes Pydantic will
    accept next as well as the ones it accepts now.

    A ``Mapping`` is deliberately passed through untouched rather than walked.
    No canonical field takes one, so Pydantic rejects it; converting it to a
    tuple of its keys would make the model *accept* a shape it currently
    refuses, which is a widening dressed as a scrub.

    The walk is bounded in both directions, and **raises** rather than
    truncating. Truncating would be the worse bug of the two: a silently
    shortened diff or changed-file list is a reviewer judging something other
    than the change, which is the one failure this whole module exists to
    prevent. Refusing is loud, and a bundle that trips a ceiling is a caller
    defect, not evidence.
    """
    if isinstance(value, str):
        return scrub_secrets(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        # errors="replace" rather than a raise: a diff off a pipe may carry a
        # stray byte, and refusing the whole evidence bundle over one would
        # leave the reviewer with nothing to judge. A mangled character is
        # visible; an unscrubbed credential is not.
        return scrub_secrets(bytes(value).decode("utf-8", errors="replace"))
    if isinstance(value, Mapping):
        return value
    if isinstance(value, Iterable):
        if _depth >= _MAX_NESTING_DEPTH:
            raise ValueError(
                f"review evidence nests deeper than {_MAX_NESTING_DEPTH} levels; "
                "a canonical field is a string or a flat sequence of strings, so "
                "this is a caller handing the builder a structure it should have "
                "flattened."
            )
        walked: list[Any] = []
        for item in value:
            if len(walked) >= _MAX_SEQUENCE_ITEMS:
                raise ValueError(
                    f"review evidence sequence exceeds {_MAX_SEQUENCE_ITEMS} "
                    "items. An unbounded iterable would walk here forever, so "
                    "the builder refuses it rather than hanging the boundary "
                    "that was supposed to be a pure function of a value."
                )
            walked.append(_scrubbed(item, _depth + 1))
        return tuple(walked)
    return value


def build_review_evidence(source: Mapping[str, Any]) -> ReviewEvidence:
    """Canonical evidence from an arbitrary bundle, copying only what is allowed.

    *source* may carry anything — an implementer's whole result envelope, a
    director's turn record. Only :data:`CANONICAL_FIELDS` are read. Unknown keys
    are not inspected, not logged and not reported: there is nothing to report,
    because a key that is never read cannot leak, and naming it in an error
    would put private content into a message.

    Free text is scrubbed for secrets on the way through, after being
    normalised into the shapes the scrub can read — see :func:`_scrubbed`.
    A diff is the most likely place for a credential to have been committed by
    accident, and a reviewer is a fresh external process that should never be
    the thing that first sees one.
    """
    picked: dict[str, Any] = {
        field: _scrubbed(source[field]) for field in CANONICAL_FIELDS if field in source
    }
    return ReviewEvidence(**picked)


def private_markers_in(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Private field names present in *payload*, for the belt-level assertion.

    Returns names only, never values: a leak detector that echoes the leak is
    itself a disclosure.
    """
    return tuple(sorted(PRIVATE_MARKERS & set(payload)))
