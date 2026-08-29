"""``Fact``, ``StandardDecision``, ``Charter`` and the ``DecisionEngine`` protocol.

Pure data + one protocol. No I/O, no repo reads, no subprocesses — importing
this module must stay free of side effects so a recorded fact ledger can be
replayed offline (epic #11752: "no conformance claim depends on an external
service being up").

Naming (deliberate, #11749): issue #11749 and epic #11752 call this type
``PolicyDecision``. That name was already taken — ``merge_policy.PolicyDecision``
is the live merge-policy classification of one change against ``policy.yaml``,
and the two are genuinely different questions ("may this PR merge" versus "does
this article hold"). One name for two meanings in one ``src/`` is exactly what
ADR-0053 forbids, and this is the layer whose whole job is vocabulary, so the
new type took the new name rather than collapsing into the old one or churning
a live actuator this change was not scoped to touch.

``StandardDecision`` and not ``ArticleDecision``: the type is keyed by
``(standard, subject)`` and carries a ``standard`` field, so it is named after
its own discriminator. Epic #11752 is explicit that "building standards are the
most important enforceable class of Articles, not the whole of Articles" —
``ArticleDecision`` would claim the whole PAAA Articles layer for a type that
today decides one standard at a time.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field, computed_field

from adr_conformance_remediation import RemediationAction

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

#: What a ``Fact`` may carry. Deliberately scalar: a fact is one observation,
#: so anything that would need a nested object is two facts, not one. ``bool``
#: leads the union because pydantic's smart-union resolves in declaration
#: order under a strict first pass, and ``True`` must round-trip as ``bool``
#: rather than collapsing into ``int`` (``bool`` is an ``int`` subclass).
FactValue = bool | int | float | str


class Fact(BaseModel):
    """One observation about one subject. Carries no judgement.

    ``standard`` names the article the observation is evidence for
    (``"adr_enforcement"``, ``"adr_conformance"``); ``subject`` names what was
    observed (``"ADR-0091"``, ``"src/foo.py"``); ``key``/``value`` is the
    observation itself; ``source`` identifies the collector so a surprising
    fact can be traced back to the code that produced it.
    """

    standard: str
    subject: str
    key: str
    value: FactValue
    observed_at: datetime
    source: str

    @computed_field
    @property
    def fact_key(self) -> str:
        """Snapshot identity of this observation: ``standard|subject|key``.

        Serialized (not an input field) purely so
        ``file_util.compact_jsonl_latest_by_key`` can give ``facts.jsonl``
        snapshot semantics — the newest observation per identity survives, so
        the ledger is bounded at "one row per fact" instead of growing by a
        full fact set every tick. Round-trips are unaffected: pydantic ignores
        the extra key on parse and equality is over the declared fields.
        """
        return f"{self.standard}|{self.subject}|{self.key}"


class DecisionStatus(StrEnum):
    """The four answers a standard can give about one subject.

    ``COMPLIANT`` — the article holds. ``VIOLATED`` — it does not, and nothing
    excuses that. ``EXEMPT`` — an allow-list says this subject legitimately
    cannot satisfy the article (permanent, justified). ``GRANDFATHERED`` — it
    does not hold, but the violation predates the gate and is carried by a
    shrink-only baseline (temporary, owed).

    The difference between the last two is the difference between the ADR
    enforcement exemption lane (``docs/standards/adr_enforcement/
    exemptions.md``) and its baseline lane
    (``tests/architecture/adr_enforcement_baseline.json``) — the two lanes
    HydraFlow already had, given one vocabulary.
    """

    COMPLIANT = "compliant"
    VIOLATED = "violated"
    EXEMPT = "exempt"
    GRANDFATHERED = "grandfathered"


class StandardDecision(BaseModel):
    """One judgement per ``(standard, subject)``, with the evidence attached.

    ``blocking`` is separate from ``status`` on purpose: a violation that a
    ratchet grandfathers is still a violation of the article, and a standard
    may legitimately decide that some violations do not stop a merge. Actuators
    read ``blocking`` to decide whether to gate and ``remediation`` to decide
    what to do about it; they never re-derive either from ``status``.
    """

    standard: str
    subject: str
    status: DecisionStatus
    blocking: bool
    reason: str = ""
    remediation: RemediationAction | None = None
    facts: list[Fact] = Field(default_factory=list)


class CharterArticles(BaseModel):
    """The ``articles`` block of a repo charter — which standards are in force.

    Minimal on purpose. ``charter.yaml`` and its full loader are #11748; this
    is the slice the decision seam needs (``Charter.articles.standards``
    selects which collectors run and which standards the engine decides), so
    the protocol below can carry its real signature before that lands.
    """

    standards: list[str] = Field(default_factory=list)


class Charter(BaseModel):
    """A repo's governing declaration, as far as the decision seam sees it."""

    articles: CharterArticles = Field(default_factory=CharterArticles)

    @classmethod
    def for_standards(cls, *standards: str) -> Charter:
        """A charter placing exactly *standards* in force."""
        return cls(articles=CharterArticles(standards=list(standards)))

    def governs(self, standard: str) -> bool:
        """Is *standard* in force? An empty ``standards`` list governs all.

        Fail-OPEN is correct here and only here: an empty article list is "no
        charter has been written yet", not "nothing is enforced". Silently
        deciding nothing would turn the day #11748's loader mis-parses
        ``charter.yaml`` into a green run over zero standards.
        """
        return not self.articles.standards or standard in self.articles.standards


@runtime_checkable
class DecisionEngine(Protocol):
    """Normalized facts in, typed decisions out. Nothing else.

    An implementation MUST NOT run pytest, inspect git, launch agents, touch
    worktrees, repair code, schedule, route models, manage PRs, or own
    lifecycle state (epic #11752). Everything an implementation needs to answer
    with must already be in *facts*; if it isn't, the fix is a collector, not a
    read inside the engine.

    :class:`policy.python_engine.PythonDecisionEngine` is the reference
    implementation; #11750's OPA pilot implements the same protocol and is
    parity-tested against it.
    """

    def decide(
        self, facts: Sequence[Fact], charter: Charter | None = None
    ) -> list[StandardDecision]:
        """Judge every ``(standard, subject)`` present in *facts*."""
        ...
