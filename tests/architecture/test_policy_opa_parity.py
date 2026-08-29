"""Rego decides what Python decides, ADR by ADR — pilot #11750's measurement 1.

Marked ``opa`` and therefore deselected by default (``pyproject.toml``
``addopts``), exactly like the ``docker`` marker: these tests need the pinned
binary ``make opa-install`` writes to ``.opa/opa``. ``make opa-test`` runs
them. The engine's *degradation* contract — what happens when the binary is
absent — needs no binary and is tested unmarked in
``tests/test_policy_opa_engine.py``.

**Why this comparison can fail**, which is the only thing that makes it worth
running. The two engines share their input (the same ``Fact`` records, from the
same collector) and nothing else:

* ``PythonDecisionEngine`` walks an ordered ``if`` ladder in
  ``_decide_enforcement`` and builds a ``StandardDecision`` in Python.
* ``OpaDecisionEngine`` serializes those facts to a JSON document, hands it to
  a separate process running ``policy/adr_enforcement.rego``, and parses the
  result back. Rego's evaluation is unordered and its default on an absent key
  is *the rule does not fire* — the opposite of the Python engine's
  fail-closed ``MissingFactError`` — so a mis-stated precedence, a dropped
  conjunct, a typo'd fact name, or a JSON round-trip that mangles a bool all
  show up here as a divergence and nowhere else.

**Anti-vacuity is asserted, not assumed.** Two engines can agree by both
returning nothing, or by a corpus that only exercises one arm. So:
``test_parity_corpus_reaches_every_status`` pins that the synthetic corpus
spans all four statuses, ``test_parity_spans_the_whole_accepted_population``
pins that the live comparison is over every Accepted ADR, and
``test_a_mutated_policy_is_caught_by_the_parity_comparison`` runs the same
comparison against deliberately broken copies of the policy and requires each
one to diverge. If the comparison ever stops observing its subject, that last
test goes green-on-broken and reddens.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from policy.facts import STANDARD_ADR_ENFORCEMENT, collect_adr_enforcement_facts
from policy.models import Charter, CharterArticles, DecisionStatus, Fact
from policy.opa_engine import POLICY_REL, OpaDecisionEngine
from policy.python_engine import PythonDecisionEngine
from policy.store import facts_from_jsonl, facts_to_jsonl

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from policy.models import StandardDecision

pytestmark = pytest.mark.opa

REPO = Path(__file__).resolve().parents[2]
OBSERVED_AT = datetime(2026, 8, 29, 9, 30, tzinfo=UTC)

#: Every enforcement class the classifier can emit, crossed with every lane and
#: every ADR-0123 authority direction.
_CLASSES = ("REAL", "WEAK", "MISSING")
_FLAGS = (False, True)
_BINDS = ("work", "factory", "both", "unknown")

#: The two assurance classes the composition probe distinguishes. Both charters
#: are run through every parity assertion: a probe that only fires under one of
#: them would otherwise be parity-tested on one side only.
_CHARTERS: tuple[tuple[str, Charter], ...] = (
    ("internal", Charter(articles=CharterArticles(assurance="internal"))),
    ("regulated", Charter(articles=CharterArticles(assurance="regulated-phi"))),
)


def _facts_for(
    subject: str,
    *,
    enforcement_class: str,
    in_baseline_snapshot: bool,
    resolved: bool,
    exempt: bool,
    binds: str,
) -> list[Fact]:
    observations: list[tuple[str, str | bool]] = [
        ("enforcement_class", enforcement_class),
        ("in_baseline_snapshot", in_baseline_snapshot),
        ("resolved", resolved),
        ("exempt", exempt),
        ("binds", binds),
    ]
    return [
        Fact(
            standard=STANDARD_ADR_ENFORCEMENT,
            subject=subject,
            key=key,
            value=value,
            observed_at=OBSERVED_AT,
            source="tests.architecture.test_policy_opa_parity",
        )
        for key, value in observations
    ]


def _exhaustive_corpus() -> list[Fact]:
    """One subject per point in the full
    ``class x snapshot x resolved x exempt x binds`` space (96 subjects).

    Exhaustive rather than sampled: a sampled parity corpus is the shape that
    agrees everywhere it looks and diverges where it doesn't.
    """
    facts: list[Fact] = []
    for index, (cls, snap, res, exempt, binds) in enumerate(
        itertools.product(_CLASSES, _FLAGS, _FLAGS, _FLAGS, _BINDS)
    ):
        facts.extend(
            _facts_for(
                f"ADR-{index + 1:04d}",
                enforcement_class=cls,
                in_baseline_snapshot=snap,
                resolved=res,
                exempt=exempt,
                binds=binds,
            )
        )
    return facts


def _live_corpus() -> list[Fact]:
    """The real ADR corpus, round-tripped through the JSONL ledger.

    The round trip is load-bearing: the epic's claim is that a decision is
    reproducible offline from ``facts.jsonl``, so both engines must be judged
    on the *written* evidence, not on live objects.
    """
    return facts_from_jsonl(
        facts_to_jsonl(collect_adr_enforcement_facts(REPO, observed_at=OBSERVED_AT))
    )


def _keyed(decisions: Sequence[StandardDecision]) -> dict[str, tuple[object, ...]]:
    """The comparable core of a decision: everything but the echoed facts."""
    return {
        d.subject: (d.standard, d.status, d.blocking, d.reason, d.remediation)
        for d in decisions
    }


def _divergences(
    facts: Sequence[Fact],
    *,
    engine: OpaDecisionEngine,
    charter: Charter | None = None,
) -> dict[str, dict[str, object]]:
    """Per-subject disagreement between the two engines, ready to print."""
    python = _keyed(PythonDecisionEngine().decide(facts, charter))
    rego = _keyed(engine.decide(facts, charter))
    return {
        subject: {
            "python": python.get(subject, "<absent>"),
            "opa": rego.get(subject, "<absent>"),
        }
        for subject in sorted(set(python) | set(rego))
        if python.get(subject) != rego.get(subject)
    }


def _report(divergences: dict[str, dict[str, object]]) -> str:
    return "\n".join(
        f"  {subject}\n    python: {sides['python']}\n    opa:    {sides['opa']}"
        for subject, sides in divergences.items()
    )


# ---------------------------------------------------------------------------
# Measurement 1 — parity
# ---------------------------------------------------------------------------


def test_the_pinned_binary_is_present_and_is_the_version_the_pilot_measured() -> None:
    """These tests are meaningless against a different OPA; pin what ran."""
    state = OpaDecisionEngine(repo_root=REPO).availability()

    assert state.available, state.reason
    assert state.version.startswith("1."), (
        f"pilot #11750 measured OPA 1.x; this host has {state.version!r}. "
        "Re-run `make opa-install` or re-measure before trusting the verdict."
    )


def test_opa_reproduces_python_for_every_accepted_adr() -> None:
    """Whole-map equality over the real corpus, not a sample."""
    engine = OpaDecisionEngine(repo_root=REPO)

    divergences = _divergences(_live_corpus(), engine=engine)

    assert not divergences, (
        "OpaDecisionEngine diverged from PythonDecisionEngine on the live ADR "
        f"corpus:\n{_report(divergences)}"
    )


@pytest.mark.parametrize(
    ("assurance", "charter"), _CHARTERS, ids=[c[0] for c in _CHARTERS]
)
def test_opa_reproduces_python_across_the_exhaustive_fact_space(
    assurance: str, charter: Charter
) -> None:
    """Every combination of class, lane and authority direction, under both
    assurance classes — not only the ones the repo reaches."""
    engine = OpaDecisionEngine(repo_root=REPO)

    divergences = _divergences(_exhaustive_corpus(), engine=engine, charter=charter)

    assert not divergences, (
        "OpaDecisionEngine diverged from PythonDecisionEngine on the exhaustive "
        f"class x lane x binds corpus under a {assurance} charter:"
        f"\n{_report(divergences)}"
    )


def test_opa_and_python_agree_on_the_blocking_set() -> None:
    """``blocking`` is what a gate reads; compare it on its own too."""
    facts = _exhaustive_corpus()
    engine = OpaDecisionEngine(repo_root=REPO)

    opa_blocking = {d.subject for d in engine.decide(facts) if d.blocking}

    assert opa_blocking == {
        d.subject for d in PythonDecisionEngine().decide(facts) if d.blocking
    }


def test_opa_honours_the_charter_the_same_way_python_does() -> None:
    """A charter that does not place the standard in force decides nothing —
    on both sides, so 'no decisions' can never be a silent parity pass."""
    facts = _exhaustive_corpus()
    charter = Charter.for_standards("testing")
    engine = OpaDecisionEngine(repo_root=REPO)

    assert engine.decide(facts, charter) == []
    assert PythonDecisionEngine().decide(facts, charter) == []


# ---------------------------------------------------------------------------
# Anti-vacuity — the comparison above must be able to fail
# ---------------------------------------------------------------------------


def test_parity_corpus_reaches_every_status() -> None:
    """A parity test whose corpus reaches one status proves only that both
    engines can say one word."""
    statuses = {d.status for d in PythonDecisionEngine().decide(_exhaustive_corpus())}

    assert statuses == set(DecisionStatus), f"corpus reached only {statuses}"


def test_the_regulated_charter_actually_changes_decisions() -> None:
    """Anti-vacuity for the probe: the two charters must reach DIFFERENT
    answers over the corpus, on both engines. If they did not, running every
    parity assertion twice would prove nothing twice."""
    corpus = _exhaustive_corpus()
    engine = OpaDecisionEngine(repo_root=REPO)
    internal, regulated = (charter for _, charter in _CHARTERS)

    opa_internal = _keyed(engine.decide(corpus, internal))
    opa_regulated = _keyed(engine.decide(corpus, regulated))

    assert opa_internal != opa_regulated
    assert _keyed(PythonDecisionEngine().decide(corpus, internal)) != _keyed(
        PythonDecisionEngine().decide(corpus, regulated)
    )


def test_parity_spans_the_whole_accepted_population() -> None:
    """The live comparison covers every Accepted ADR, and there are many."""
    engine = OpaDecisionEngine(repo_root=REPO)

    subjects = {d.subject for d in engine.decide(_live_corpus())}

    assert len(subjects) > 50, f"ADR corpus unexpectedly small: {len(subjects)}"


#: Each entry breaks the policy in a way a real edit could. ``old`` must occur
#: in the policy (asserted below, so a rewritten policy cannot silently make
#: these mutations no-ops) and the mutated policy must diverge from Python.
_MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "exempt-loses-to-the-baseline-lane",
        'else := "exempt" if obs.exempt\n',
        'else := "exempt" if {\n\tobs.exempt\n\tnot obs.in_baseline_snapshot\n}\n',
    ),
    (
        "grandfathering-ignores-resolved",
        'else := "grandfathered" if {\n\tobs.in_baseline_snapshot\n\tnot obs.resolved\n}\n',
        'else := "grandfathered" if obs.in_baseline_snapshot\n',
    ),
    (
        "weak-stops-counting-as-debt",
        'debt_classes := {"WEAK", "MISSING"}',
        'debt_classes := {"MISSING"}',
    ),
    (
        "violations-stop-blocking",
        '"blocking": verdict == "violated",',
        '"blocking": false,',
    ),
    (
        "remediation-never-files-an-issue",
        'remediation(verdict) := "file_issue" if verdict == "violated"',
        'remediation(verdict) := "none" if verdict == "violated"',
    ),
    (
        "the-probe-stops-reading-the-charter",
        'regulated if startswith(object.get(input, ["charter", "assurance"], "internal"), "regulated-")',
        "regulated if true",
    ),
    (
        "the-probe-forgets-binds-both",
        'obs.binds in {"factory", "both"}',
        'obs.binds in {"factory"}',
    ),
)


@pytest.mark.parametrize(
    ("name", "old", "new"), _MUTATIONS, ids=[m[0] for m in _MUTATIONS]
)
def test_a_mutated_policy_is_caught_by_the_parity_comparison(
    tmp_path: Path, name: str, old: str, new: str
) -> None:
    """The comparison is not vacuous: break the policy, and it must redden.

    This is the guard on the guard. Every mutation below is a plausible edit to
    ``adr_enforcement.rego``; if any of them can be made without the parity
    comparison noticing, then parity is being asserted over something other
    than the decision and the green above means nothing.
    """
    source = (REPO / POLICY_REL).read_text(encoding="utf-8")
    assert old in source, (
        f"mutation {name!r} no longer applies — the policy was rewritten and "
        "this anti-vacuity check has stopped observing its subject. Re-target "
        "the mutation at the rule that replaced it."
    )
    mutated = tmp_path / "adr_enforcement.rego"
    mutated.write_text(source.replace(old, new), encoding="utf-8")
    engine = OpaDecisionEngine(repo_root=REPO, policy=mutated)

    corpus = _exhaustive_corpus()
    divergences: dict[str, dict[str, object]] = {}
    for _, charter in _CHARTERS:
        divergences |= _divergences(corpus, engine=engine, charter=charter)

    assert divergences, (
        f"mutation {name!r} changed the policy's decision rules and the parity "
        "comparison did not notice. The comparison is vacuous."
    )


# ---------------------------------------------------------------------------
# The offline guarantee (#11687)
# ---------------------------------------------------------------------------


def _code_of(source: str) -> str:
    """*source* with Rego line comments stripped.

    The policy's own header names the builtins it must never use, so a raw
    substring scan would flag the documentation instead of the code. Comments
    start at an unquoted ``#``.
    """
    lines: list[str] = []
    for line in source.splitlines():
        cut = len(line)
        for index, char in enumerate(line):
            if char == "#" and line.count('"', 0, index) % 2 == 0:
                cut = index
                break
        lines.append(line[:cut])
    return "\n".join(lines)


#: Builtins that would let a decision depend on something outside the
#: evaluation — the network, the clock, the host, or the caller's stderr.
_FORBIDDEN_BUILTINS: tuple[str, ...] = (
    "http.send",
    "net.lookup_ip_addr",
    "opa.runtime",
    "time.now_ns",
    "rand.intn",
    "trace(",
)


def test_the_policy_cannot_reach_the_network_at_decision_time() -> None:
    """No conformance claim may depend on a service being up. The pinned
    binary is invoked with a local file and stdin; the policy itself must not
    contain a builtin that could reach outward, read the host, or be
    non-deterministic."""
    code = _code_of((REPO / POLICY_REL).read_text(encoding="utf-8"))

    forbidden = [builtin for builtin in _FORBIDDEN_BUILTINS if builtin in code]

    assert not forbidden, (
        f"{POLICY_REL} uses {forbidden}, which can reach outside the evaluation. "
        "A decision must be reproducible offline from a clean checkout (#11687)."
    )


def test_the_network_guard_reads_code_and_not_only_comments() -> None:
    """Anti-vacuity: the scan above must see a builtin the policy actually
    calls, and must NOT see one that only appears in its documentation."""
    assert _FORBIDDEN_BUILTINS[0] in _code_of(f"x := {_FORBIDDEN_BUILTINS[0]}({{}})")
    assert _FORBIDDEN_BUILTINS[0] not in _code_of(
        f"# never use {_FORBIDDEN_BUILTINS[0]}"
    )
