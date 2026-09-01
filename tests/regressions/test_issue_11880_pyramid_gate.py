"""The test-pyramid standard gates changes it can decide, and only those.

`docs/standards/testing/README.md` calls skipping a layer "a procedural failure
— not a judgment call", and the standard's own `standard.yaml` carries the
normative matrix of WHEN each layer is required. Nothing enforced it: six
load-bearing fixes merged on 2026-08-31 with unit tests only, including #11853
whose defect a unit test could not see by construction.

**What blocks, and why only that.** The gate blocks exactly where two things
hold: the standard says `required`, and the change's shape is derivable
unambiguously from its conventional-commit type. "Is this load-bearing?" is not
statically decidable — but "this PR contains a `fix(` commit, and the standard
says a bug fix requires a scenario" is. The gate reads an obligation the
standard already declares rather than inventing one.

`feat(` maps to NO shape on purpose: it may be a new loop, a new port method, or
neither, and those rows disagree. Gating on a guess is how a gate earns its way
into being disabled — #11881 is this session's own example, where a gate I
shipped rejected a legal value and blocked a real PR.

`conditional` never blocks. It is the standard's own word for "it depends", and
a machine cannot resolve that.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest

from policy.facts import (
    collect_test_pyramid_facts,
    requirement_matrix,
    shape_of_commit,
)
from policy.models import DecisionStatus
from policy.python_engine import PythonDecisionEngine

_STANDARD = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "standards"
    / "testing"
    / "standard.yaml"
)


class _GovernsAll:
    def governs(self, standard: str) -> bool:  # noqa: ARG002 - stub
        return True


def _decide(paths: list[str], subjects: list[str]):
    facts = collect_test_pyramid_facts(
        paths, observed_at=datetime.now(UTC), commit_subjects=subjects
    )
    return PythonDecisionEngine().decide(facts, charter=_GovernsAll())[0]


def test_a_bug_fix_without_a_scenario_is_blocked() -> None:
    """Tonight's exact shape, and the reason the gate exists."""
    d = _decide(["src/a.py", "tests/regressions/t.py"], ["fix(x): y"])
    assert d.status is DecisionStatus.VIOLATED
    assert d.blocking is True
    assert "scenario" in d.reason


def test_a_bug_fix_with_a_scenario_does_not_block() -> None:
    """Sandbox is `conditional` for a bug fix, so its absence advises only."""
    d = _decide(
        ["src/a.py", "tests/regressions/t.py", "tests/scenarios/s.py"], ["fix(x): y"]
    )
    assert d.blocking is False


def test_a_pure_refactor_without_a_scenario_does_not_block() -> None:
    """The standard marks scenario `not_required` for a refactor.

    Without this the gate would fail every ordinary refactor — the false
    positive that gets a gate disabled.
    """
    d = _decide(["src/a.py", "tests/regressions/t.py"], ["refactor(x): y"])
    assert d.blocking is False


def test_an_ambiguous_commit_type_never_blocks() -> None:
    """`feat(` spans rows that disagree, so it asserts no obligation."""
    assert shape_of_commit("feat(gateway): x") == ""
    d = _decide(["src/a.py", "tests/regressions/t.py"], ["feat(x): y"])
    assert d.blocking is False
    assert "no declared shape" in d.reason


def test_a_docs_only_change_is_exempt() -> None:
    d = _decide(["docs/x.md"], ["docs(x): y"])
    assert d.status is DecisionStatus.EXEMPT
    assert d.blocking is False


def test_a_mixed_pr_is_judged_by_its_strictest_shape() -> None:
    """A PR carrying a `fix(` alongside a `docs(` still contains a bug fix.

    Taking the laxest shape would let any obligation be dissolved by adding a
    docs commit — a one-line bypass of the whole gate.
    """
    d = _decide(["src/a.py", "tests/regressions/t.py"], ["docs(a): x", "fix(b): y"])
    assert d.blocking is True


def test_the_matrix_is_read_from_the_standard_not_restated() -> None:
    """Two writers, one table: the YAML is normative and drift-checked against
    the README, so a copy in the policy module would be a third writer."""
    matrix = requirement_matrix(_STANDARD.read_text("utf-8"))
    assert matrix["Bug fix"]["scenario"] == "required"
    assert matrix["Pure refactor with no behavior change"]["scenario"] == (
        "not_required"
    )


def test_an_unreadable_standard_does_not_block() -> None:
    """A gate that cannot read its own standard must not block on a guess.

    Fail-open is the correct direction HERE specifically because the failure is
    in the gate's own evidence, not in the change under test.
    """
    assert requirement_matrix("") == {}
    facts = collect_test_pyramid_facts(
        ["src/a.py"], observed_at=datetime.now(UTC), commit_subjects=["fix(x): y"]
    )
    by_key = {f.key: f.value for f in facts}
    assert by_key["shape"] == "Bug fix"


def test_the_pr_title_decides_the_shape_not_the_branch_commits() -> None:
    """The repo squash-merges, so the title IS the commit that lands.

    Found by this gate blocking its OWN pull request: the branch carried a
    `fix(audit): ...` fixup correcting code added in the same PR, so the gate
    read the shape as "Bug fix" and demanded a scenario for a change that
    lands as a single `feat(`. The fixup never reaches history — gating on it
    means gating on a shape that does not ship.

    Same class as #11881, where a gate I shipped rejected a legal value: both
    times the gate judged something other than the thing under judgement.
    """
    import os
    from unittest.mock import patch

    from hydraflow_audit.checks import p10_tdd

    src = ["src/a.py", "tests/regressions/t.py"]
    commits = ["fix(a): fixup", "feat(x): the actual change"]

    def _status(title: str) -> str:
        env = {p10_tdd._PR_TITLE_ENV: title} if title else {}
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(p10_tdd, "_pr_gate_preflight", return_value=("base", None)),
            patch.object(p10_tdd, "_changed_paths_since", return_value=src),
            patch.object(p10_tdd, "_pr_commit_subjects", return_value=commits),
        ):
            if not title:
                os.environ.pop(p10_tdd._PR_TITLE_ENV, None)
            ctx = type("C", (), {"root": Path(".")})()
            return p10_tdd._changes_ship_the_layers_the_standard_requires(
                ctx
            ).status.name

    assert _status("feat(x): the actual change") == "PASS", (
        "the fixup commit still decided the shape — the gate blocks a PR that "
        "lands as feat("
    )
    # And the fallback still works when CI does not supply a title, or a local
    # run has no PR at all: the commits are then the only evidence there is.
    assert _status("") == "FAIL"


def test_a_titled_bug_fix_still_blocks() -> None:
    """Anti-vacuity for the test above.

    Reading the title must not become a way to never block — a `fix(` title
    with no scenario is the shape the gate exists for.
    """
    import os
    from unittest.mock import patch

    from hydraflow_audit.checks import p10_tdd

    with (
        patch.dict(os.environ, {p10_tdd._PR_TITLE_ENV: "fix(x): y"}, clear=False),
        patch.object(p10_tdd, "_pr_gate_preflight", return_value=("base", None)),
        patch.object(
            p10_tdd,
            "_changed_paths_since",
            return_value=["src/a.py", "tests/regressions/t.py"],
        ),
        patch.object(p10_tdd, "_pr_commit_subjects", return_value=["docs(a): x"]),
    ):
        ctx = type("C", (), {"root": Path(".")})()
        got = p10_tdd._changes_ship_the_layers_the_standard_requires(ctx)
    assert got.status.name == "FAIL", "a fix( title with no scenario must block"


def test_the_check_never_emits_a_blocking_warn() -> None:
    """WARN reddens this audit, so a non-blocking verdict must PASS.

    `overall_exit_code` counts WARN as a red audit unless the check is
    allow-listed as telemetry (a history scan that cannot blame the PR) or
    advisory (a corpus scan). P10.8 is neither — it judges the change under
    test. Emitting WARN for a `conditional` cell or an ambiguous `feat(` would
    turn the standard's own "it depends" into a hard CI stop, which is the
    false positive that gets a gate disabled.
    """
    import os
    from unittest.mock import patch

    from hydraflow_audit.checks import p10_tdd

    src = ["src/a.py", "tests/regressions/t.py"]
    seen = set()
    for title in ("feat(x): y", "refactor(x): y", "fix(x): y", "docs(x): y"):
        with (
            patch.dict(os.environ, {p10_tdd._PR_TITLE_ENV: title}, clear=False),
            patch.object(p10_tdd, "_pr_gate_preflight", return_value=("base", None)),
            patch.object(p10_tdd, "_changed_paths_since", return_value=src),
            patch.object(p10_tdd, "_pr_commit_subjects", return_value=[title]),
        ):
            ctx = type("C", (), {"root": Path(".")})()
            seen.add(p10_tdd._changes_ship_the_layers_the_standard_requires(ctx).status)
    names = {s.name for s in seen}
    assert "WARN" not in names, f"P10.8 emitted a CI-reddening WARN: {names}"
    assert names == {"PASS", "FAIL"}, f"expected only PASS/FAIL, got {names}"


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("fix(a): x", "Bug fix"),
        ("refactor(a): x", "Pure refactor with no behavior change"),
        ("docs(a): x", "New ADR / wiki / config"),
        ("chore(a): x", "New ADR / wiki / config"),
        ("feat(a): x", ""),
        ("no conventional prefix", ""),
    ],
)
def test_shape_derivation(subject: str, expected: str) -> None:
    assert shape_of_commit(subject) == expected
