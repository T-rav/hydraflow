"""Fact collectors — the only half of the seam allowed to read the world.

Every repo read that a decision depends on happens here: scanning the ADR
corpus, loading the frozen enforcement baseline, parsing the exemption
allow-list, flattening a loop's in-flight ``AdrConformance``. The engine gets
the resulting ``Fact`` records and nothing else, which is what makes a decision
reproducible from ``facts.jsonl`` offline.

Collectors emit **primitive** observations, never derived verdicts. The ADR
enforcement collector emits ``in_baseline_snapshot`` / ``resolved`` / ``exempt``
rather than a single ``grandfathered`` boolean, precisely so the engine has to
re-derive ``baseline_snapshot - resolved - exempted`` for itself. A collector
that handed the engine the answer would make the parity test in
``tests/architecture/test_policy_adr_enforcement_parity.py`` tautological —
both sides would be reading the same helper's output rather than reaching the
same conclusion by different routes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from adr_conformance import (
    accepted_adrs,
    classify_adr_enforcement,
    load_enforcement_baseline,
    parse_exemptions,
)
from package_resources import ResourceNotFoundError, checkout_path
from policy.models import Fact

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence
    from datetime import datetime

    from adr_conformance import AdrConformance

#: Static enforcement debt: does each Accepted ADR's decision bind to a real,
#: runnable, asserting check? Gated by
#: ``tests/architecture/test_adr_enforcement_ratchet.py``.
STANDARD_ADR_ENFORCEMENT = "adr_enforcement"

#: Runtime conformance: do the checks an ADR cites still pass? Actuated by
#: ``AdrConformanceLoop`` (ADR-0100).
STANDARD_ADR_CONFORMANCE = "adr_conformance"

#: Test-pyramid coverage: does a change to a load-bearing source module carry
#: all three layers? ``docs/standards/testing/README.md`` calls skipping one
#: "a procedural failure — not a judgment call", but nothing checked it, and
#: six load-bearing fixes merged on 2026-08-31 with unit tests only (#11880).
STANDARD_TEST_PYRAMID = "test_pyramid"

#: Every standard this module can collect for — the default charter.
COLLECTED_STANDARDS: tuple[str, ...] = (
    STANDARD_ADR_ENFORCEMENT,
    STANDARD_ADR_CONFORMANCE,
    STANDARD_TEST_PYRAMID,
)

_ENFORCEMENT_SOURCE = "policy.facts.collect_adr_enforcement_facts"
_CONFORMANCE_SOURCE = "policy.facts.conformance_facts"
_PYRAMID_SOURCE = "policy.facts.collect_test_pyramid_facts"

#: Where each layer lives. Derived from the standard's own diagram
#: rather than re-stated: `tests/regressions/` and flat `tests/` are the
#: unit layer, `tests/scenarios/` is MockWorld, `tests/sandbox_scenarios/`
#: is e2e. A path that matches none of these is not a test.
_LAYER_PREFIXES: dict[str, str] = {
    "scenario": "tests/scenarios/",
    "sandbox": "tests/sandbox_scenarios/",
}


def adr_subject(number: int) -> str:
    """The canonical subject id for an ADR number: ``ADR-0091``."""
    return f"ADR-{number:04d}"


def collect_adr_enforcement_facts(
    repo_root: Path, *, observed_at: datetime
) -> list[Fact]:
    """Observe the enforcement-debt evidence for every Accepted ADR.

    Five facts per ADR, all primitive:

    * ``enforcement_class`` — ``REAL`` / ``WEAK`` / ``MISSING``
      (``adr_conformance.classify_adr_enforcement``).
    * ``in_baseline_snapshot`` — is the ADR in the frozen landing snapshot?
    * ``resolved`` — has its debt been claimed paid in the baseline JSON?
    * ``exempt`` — is it allow-listed as process-only?
    * ``binds`` — ``work`` / ``factory`` / ``both`` / ``unknown``
      (``adr_index.ADR.binds``, ADR-0123): which direction the ADR's rule
      constrains. A fact about the SUBJECT, joined at decision time to a fact
      about the repo (``Charter.is_regulated``, ADR-0143) by the composition
      probe in ``PythonDecisionEngine._decide_enforcement``.

    The engine derives ``grandfathered`` from the middle two; see the module
    docstring for why that derivation is not done here.
    """
    adrs = accepted_adrs(repo_root)
    classes = {adr.number: classify_adr_enforcement(adr, repo_root) for adr in adrs}
    snapshot, resolved = load_enforcement_baseline(repo_root)
    exempted = frozenset(parse_exemptions(repo_root))
    binds_by_number = {adr.number: adr.binds for adr in adrs}

    facts: list[Fact] = []
    for number in sorted(classes):
        subject = adr_subject(number)
        observations: list[tuple[str, bool | str]] = [
            ("enforcement_class", classes[number].value),
            ("in_baseline_snapshot", number in snapshot),
            ("resolved", number in resolved),
            ("exempt", number in exempted),
            ("binds", binds_by_number.get(number, "unknown")),
        ]
        facts.extend(
            Fact(
                standard=STANDARD_ADR_ENFORCEMENT,
                subject=subject,
                key=key,
                value=value,
                observed_at=observed_at,
                source=_ENFORCEMENT_SOURCE,
            )
            for key, value in observations
        )
    return facts


def conformance_facts(
    conf: AdrConformance,
    *,
    rename_match: str | None,
    attempts: int,
    max_attempts: int,
    observed_at: datetime,
) -> list[Fact]:
    """Flatten one in-flight ``AdrConformance`` into the facts a decision needs.

    ``rename_match`` and ``attempts`` are the loop's own observations (a
    detected pytest-node rename, the per-ADR attempt counter), not properties
    of the ADR — they are collected here for the same reason the on-disk reads
    are: so the engine sees only facts.

    ``rename_match`` is omitted rather than emitted as an empty string when
    absent. "No rename was detected" and "a rename to the empty string was
    detected" must not serialize identically.
    """
    observations: list[tuple[str, bool | int | str]] = [
        ("outcome", conf.outcome.value),
        ("kind", conf.kind.value),
        ("attempts", attempts),
        ("max_attempts", max_attempts),
    ]
    if rename_match is not None:
        observations.append(("rename_match", rename_match))
    return [
        Fact(
            standard=STANDARD_ADR_CONFORMANCE,
            subject=conf.adr_id,
            key=key,
            value=value,
            observed_at=observed_at,
            source=_CONFORMANCE_SOURCE,
        )
        for key, value in observations
    ]


def _layer_of(path: str) -> str | None:
    """Which pyramid layer a changed path belongs to, or None if not a test.

    Order matters: `tests/scenarios/` and `tests/sandbox_scenarios/` are checked
    before the generic `tests/` prefix, or every scenario would also count as a
    unit test and the standard would be trivially satisfied.
    """
    for layer, prefix in _LAYER_PREFIXES.items():
        if path.startswith(prefix):
            return layer
    if path.startswith("tests/"):
        return "unit"
    return None


#: Conventional-commit type -> the standard's "When each layer is required"
#: row (`shape` in docs/standards/testing/standard.yaml). Only types whose row
#: is UNAMBIGUOUS appear: `feat(` may be a new loop, a new port method, or
#: neither, and those rows disagree, so guessing would gate on a coin flip.
#: An unmapped type yields no shape and the decision stays report-only.
_COMMIT_TYPE_SHAPE: dict[str, str] = {
    "fix": "Bug fix",
    "refactor": "Pure refactor with no behavior change",
    "docs": "New ADR / wiki / config",
    "chore": "New ADR / wiki / config",
    "test": "Pure refactor with no behavior change",
}


def shape_of_commit(subject: str) -> str:
    """The standard's requirement-row for a conventional-commit subject.

    Empty when the type is unmapped or absent — the caller must then treat the
    verdict as advisory. Deriving a shape we are not sure of would gate a PR on
    a guess, which is how a gate earns its way into being disabled (#11881).
    """
    head = subject.split(":", 1)[0].strip()
    kind = head.split("(", 1)[0].strip().lower()
    return _COMMIT_TYPE_SHAPE.get(kind, "")


def collect_test_pyramid_facts(
    changed_paths: Sequence[str],
    *,
    observed_at: datetime,
    load_bearing_prefixes: Sequence[str] = ("src/",),
    commit_subjects: Sequence[str] = (),
) -> list[Fact]:
    """Observe which pyramid layers a change touched. No judgement.

    Pure over a path list — the caller supplies a PR's changed files (the same
    merge-base diff P10.6 already uses), so this is testable without a git
    repository and deterministic under replay.

    The subject is the CHANGE as a whole, not a module: the standard asks
    whether a load-bearing change ships three layers, and layers do not
    correspond one-to-one with modules. Naming a single module as subject would
    force an arbitrary choice among the changed ones.
    """
    layers = {layer for p in changed_paths if (layer := _layer_of(p)) is not None}
    shape = _dominant_shape(commit_subjects)
    # The collector does the reading. Falls back to an empty requirement (no
    # obligation asserted) if the standard is unreadable — a gate that cannot
    # read its own standard must not block on a guess.
    req: dict[str, str] = {}
    if shape:
        try:
            # checkout_path, not a walk up from __file__: docs/standards/ is
            # deliberately absent from the wheel, and parents[2] resolves
            # inside site-packages there (#11589).
            std = checkout_path("docs", "standards", "testing", "standard.yaml")
            req = requirement_matrix(std.read_text("utf-8")).get(shape, {})
        except (OSError, ValueError, ResourceNotFoundError):
            req = {}
    touches_source = any(
        p.startswith(tuple(load_bearing_prefixes)) and not p.startswith("tests/")
        for p in changed_paths
    )
    subject = "change"
    return [
        Fact(
            standard=STANDARD_TEST_PYRAMID,
            subject=subject,
            key=key,
            value=value,
            observed_at=observed_at,
            source=_PYRAMID_SOURCE,
        )
        for key, value in (
            ("touches_source", touches_source),
            ("has_unit", "unit" in layers),
            ("has_scenario", "scenario" in layers),
            ("has_sandbox", "sandbox" in layers),
            ("shape", shape),
            ("requires_unit", req.get("unit", "")),
            ("requires_scenario", req.get("scenario", "")),
            ("requires_sandbox", req.get("sandbox", "")),
        )
    ]


def _dominant_shape(subjects: Sequence[str]) -> str:
    """The strictest known shape across a PR's commits, or "" if none is known.

    Strictest wins because a PR mixing a `fix(` with a `docs(` still contains a
    bug fix, and the bug-fix row is the one with the obligation. A single
    unmapped-but-present type does not soften the others; it simply adds no
    claim of its own.
    """
    shapes = [s for s in (shape_of_commit(x) for x in subjects) if s]
    if not shapes:
        return ""
    # Order matches the standard's rows from most to least demanding.
    for candidate in (
        "New port method (e.g. `update_pr_branch`)",
        "New loop or runner",
        "Bug fix",
        "Pure refactor with no behavior change",
        "New ADR / wiki / config",
    ):
        if candidate in shapes:
            return candidate
    return shapes[0]


def requirement_matrix(standard_yaml: str) -> dict[str, dict[str, str]]:
    """`{shape: {layer: required|conditional|not_required}}` from the standard.

    Parsed from `docs/standards/testing/standard.yaml`, never restated here:
    the YAML is the normative encoding of the README's matrix and is already
    drift-checked against it. A second copy in this module would be a third
    writer for one table.
    """

    doc = yaml.safe_load(standard_yaml) or {}
    out: dict[str, dict[str, str]] = {}
    for row in doc.get("requirements", ()):
        shape = row.get("shape", "")
        if shape:
            out[shape] = {
                layer: row.get(layer, "not_required")
                for layer in ("unit", "scenario", "sandbox")
            }
    return out
