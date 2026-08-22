"""Honour ``Blocked by: #N`` declarations on issue bodies (#11614).

A phase-ordered epic decomposes into children that each declare their
prerequisites on a ``Blocked by:`` line. Before this module nothing in the
pipeline read those lines, so every child of an ordered epic became eligible
at the same instant — with three implement workers that means P3 and P6 get
built before P0 exists, and phases that touch the same subsystem collide.

The gate answers one question: *does this issue declare a prerequisite that
is still open?* :class:`~triage_phase.TriagePhase` asks it as a pre-classify
screen, so a blocked child never reaches the triage LLM at all.

Two properties are load-bearing:

**Fail-open, always.** An unreadable blocker, a nonexistent issue number, a
GitHub read error and a rate limit all resolve to *not blocking*. An unknown
dependency is not evidence of a dependency, and a bug on this path would
silently freeze the entire board — the failure mode is far worse than
occasionally building something a tick early. Failing open is never silent:
an unreadable blocker logs a WARNING naming it, and an exception logs a full
stack, so a systematically-unreadable board is loud rather than invisible.

**No parking.** The gate returns a verdict and nothing else. The caller
leaves the issue on its current pipeline label, so the next triage tick
re-evaluates it and a closed blocker simply unblocks it. There is no new
label, no parked state, and no second actor needed to un-park anything.

Blocker state is read exclusively through :class:`~ports.PRPort`
(``get_issue_state`` / ``get_issue_body``) — never a raw ``gh`` shell-out —
so MockWorld and the sandbox stay air-gapped.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from ports import PRPort

_T = TypeVar("_T")

logger = logging.getLogger("hydraflow.blocker_gate")

__all__ = ["BlockerGate", "BlockerVerdict", "parse_blockers"]

#: The ONLY declaration grammar this module recognises: a line whose entire
#: content is ``Blocked by:`` followed by a comma-separated list of issue
#: refs. That is what operator-filed epic children carry (see #11531/#11532);
#: the auto-decomposer emits no dependency line at all today, and the
#: ``**Depends on:**`` grammar in ``planner.py`` / ``task_graph.py`` refers to
#: PHASE numbers inside one plan ("P1"), not issue numbers — folding it in
#: here would read plan phases as GitHub issues. Nothing else is invented.
#:
#: Anchoring to a whole line is what stops prose from matching: "this was
#: blocked by a flaky test in #42" has trailing words, so it never parses.
_BLOCKED_BY_LINE = re.compile(
    r"^[ \t]*Blocked by:[ \t]*(#\d+(?:[ \t]*,[ \t]*#\d+)*)[ \t\r]*$",
    re.IGNORECASE | re.MULTILINE,
)
_ISSUE_REF = re.compile(r"#(\d+)")

#: ``PRPort.get_issue_state`` answers ``"OPEN"`` for a live issue. Anything
#: else — ``COMPLETED``, ``NOT_PLANNED``, ``UNKNOWN`` (the fail-closed answer
#: both PRManager and FakeGitHub give on a read error) or ``""`` — is treated
#: as not blocking. Only a positively-confirmed OPEN issue holds work back.
_OPEN = "OPEN"

#: States that mean "we could not establish this issue is open". Logged so a
#: systematically unreadable blocker surfaces instead of silently passing.
_UNRESOLVED_STATES = frozenset({"", "UNKNOWN"})

#: How long a blocker's state is reused. Many children of one epic reference
#: the same two or three blockers, so without this each triage tick would
#: re-read the same issue once per child. Short enough that a blocker closed
#: mid-tick unblocks its children on the next tick rather than minutes later.
_STATE_TTL_SECONDS = 60.0

#: Hard ceiling on issues visited while looking for a dependency cycle. Bounds
#: the reads a pathological (or malicious) body can provoke.
_MAX_CYCLE_NODES = 20

#: Ceiling on cached issues. Entries also expire on read, but an issue read
#: once and never asked about again would otherwise sit in the dict for the
#: life of the process — the gate is long-lived (one per phase).
_MAX_CACHE_ENTRIES = 256


def parse_blockers(body: str | None, *, self_number: int = 0) -> list[int]:
    """Return the issue numbers declared on ``Blocked by:`` lines in *body*.

    Order of first appearance is preserved, duplicates collapse, and a
    self-reference (``self_number``) is dropped — an issue cannot block
    itself, and honouring one would strand it forever.
    """
    if not body:
        return []
    found: list[int] = []
    seen: set[int] = set()
    for match in _BLOCKED_BY_LINE.finditer(body):
        for raw in _ISSUE_REF.findall(match.group(1)):
            number = int(raw)
            if number <= 0 or number == self_number or number in seen:
                continue
            seen.add(number)
            found.append(number)
    return found


@dataclass(frozen=True)
class BlockerVerdict:
    """What the gate concluded about one issue's declared prerequisites."""

    declared: tuple[int, ...] = ()
    open_blockers: tuple[int, ...] = ()

    @property
    def blocked(self) -> bool:
        """True only when at least one declared blocker is confirmed OPEN."""
        return bool(self.open_blockers)

    @property
    def reason(self) -> str:
        """Board-facing explanation naming the blockers, e.g. ``waiting on #11533``."""
        refs = ", ".join(f"#{n}" for n in self.open_blockers)
        return f"Waiting on open blocker(s): {refs}"


@dataclass
class _CacheEntry(Generic[_T]):
    """One memoised port read, stamped for TTL expiry."""

    value: _T
    stored_at: float


class BlockerGate:
    """Resolves ``Blocked by:`` declarations against live issue state.

    One instance per phase; the TTL caches are what keep a batch of epic
    children from re-reading the same two blockers once per child.
    """

    def __init__(self, *, ttl_seconds: float = _STATE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._states: dict[int, _CacheEntry[str]] = {}
        # Parsed edges, not raw bodies: an issue body runs to tens of KB and
        # the cycle walk only ever needs its ``Blocked by`` refs.
        self._edges: dict[int, _CacheEntry[tuple[int, ...]]] = {}

    async def evaluate(
        self, prs: PRPort, issue_number: int, body: str | None
    ) -> BlockerVerdict:
        """Return the blocker verdict for *issue_number*.

        Never raises: every failure path resolves to "not blocked". This
        deliberately does NOT call ``reraise_on_credit_or_bug`` — the gate
        spawns no agent, so it carries no billing signal to preserve, and the
        one thing it must never do is let an error hold the board.
        """
        declared = parse_blockers(body, self_number=issue_number)
        if not declared:
            return BlockerVerdict()

        try:
            open_blockers = await self._open_blockers(prs, declared)
            if open_blockers and await self._reaches(prs, issue_number, open_blockers):
                logger.warning(
                    "Issue #%d sits in a 'Blocked by' cycle (%s) — failing open "
                    "so the cycle cannot deadlock the board",
                    issue_number,
                    ", ".join(f"#{n}" for n in open_blockers),
                )
                return BlockerVerdict(declared=tuple(declared))
        except Exception:
            # Total by design: rate limits, transport errors, a fake that
            # answers a shape we did not expect — every one of them resolves
            # to "not blocked". Logged via ``exception`` so the stack is never
            # lost; a systematically unreadable board is loud, not silent.
            logger.exception(
                "Could not resolve blockers %s for issue #%d — failing open "
                "(an unknown dependency is not evidence of a dependency)",
                ", ".join(f"#{n}" for n in declared),
                issue_number,
            )
            return BlockerVerdict(declared=tuple(declared))

        return BlockerVerdict(
            declared=tuple(declared), open_blockers=tuple(open_blockers)
        )

    async def _open_blockers(self, prs: PRPort, declared: list[int]) -> list[int]:
        """Return the subset of *declared* that is confirmed OPEN."""
        return [n for n in declared if await self._state(prs, n) == _OPEN]

    async def _reaches(self, prs: PRPort, origin: int, seeds: list[int]) -> bool:
        """True when ``Blocked by`` edges from *seeds* lead back to *origin*.

        A cycle would otherwise wedge every issue on it permanently. Bounded
        by :data:`_MAX_CYCLE_NODES` and by a visited set, so each issue is read
        at most once per call. Exhausting the bound answers "no cycle found",
        which leaves a genuinely-blocked issue blocked — the conservative
        direction for a graph too large to walk.
        """
        frontier = list(seeds)
        visited: set[int] = {origin}
        while frontier:
            if len(visited) > _MAX_CYCLE_NODES:
                logger.warning(
                    "Cycle walk from issue #%d hit the %d-issue ceiling — "
                    "reporting no cycle",
                    origin,
                    _MAX_CYCLE_NODES,
                )
                return False
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            for nxt in await self._edges_of(prs, current):
                if nxt == origin:
                    return True
                if nxt not in visited:
                    frontier.append(nxt)
        return False

    async def _state(self, prs: PRPort, number: int) -> str:
        """Read an issue's state through the PRPort, memoised for the TTL."""
        cached = self._fresh(self._states, number)
        if cached is not None:
            return cached
        state = (await prs.get_issue_state(number) or "").upper()
        if state in _UNRESOLVED_STATES:
            logger.warning(
                "Blocker #%d could not be read (state=%r) — treating it as unblocked",
                number,
                state,
            )
        self._store(self._states, number, state)
        return state

    async def _edges_of(self, prs: PRPort, number: int) -> tuple[int, ...]:
        """Return *number*'s own declared blockers, memoised for the TTL."""
        cached = self._fresh(self._edges, number)
        if cached is not None:
            return cached
        body = await prs.get_issue_body(number) or ""
        edges = tuple(parse_blockers(body, self_number=number))
        self._store(self._edges, number, edges)
        return edges

    def _fresh(self, cache: dict[int, _CacheEntry[_T]], number: int) -> _T | None:
        """Return the cached value for *number* while it is inside the TTL."""
        entry = cache.get(number)
        if entry is None:
            return None
        if time.monotonic() - entry.stored_at >= self._ttl:
            del cache[number]
            return None
        return entry.value

    def _store(self, cache: dict[int, _CacheEntry[_T]], number: int, value: _T) -> None:
        """Memoise *value* and keep the cache bounded."""
        now = time.monotonic()
        cache[number] = _CacheEntry(value, now)
        if len(cache) <= _MAX_CACHE_ENTRIES:
            return
        for key in [k for k, e in cache.items() if now - e.stored_at >= self._ttl]:
            del cache[key]
        while len(cache) > _MAX_CACHE_ENTRIES:
            del cache[min(cache, key=lambda k: cache[k].stored_at)]
